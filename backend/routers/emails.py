"""
Email API routes.
Send emails and view email history.
"""
import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import LinkedInPost, EmailLog, EmailJob, ExtractedEmail, EmailStatus
from schemas import (
    SendEmailRequest,
    BulkSendEmailRequest,
    EmailLogResponse,
    EmailJobResponse,
    DraftEmailRequest,
    DraftEmailResponse,
    ContactResponse,
)
from services.ai_extractor import ai_extractor
from services.email_sender import EmailSender

logger = logging.getLogger("EmailJob")

router = APIRouter(prefix="/api/emails", tags=["Emails"])

email_sender = EmailSender()


async def _last_sent_to(db: AsyncSession, recipient: str) -> Optional[EmailLog]:
    """Most recent successful email to this address inside the cooldown window.

    The same hiring post surfaces under many searches, so without this the same
    recruiter gets contacted repeatedly — which is how a sending address gets
    marked as spam. Returns None when the cooldown is disabled.
    """
    if settings.email_cooldown_days <= 0:
        return None

    cutoff = datetime.utcnow() - timedelta(days=settings.email_cooldown_days)
    result = await db.execute(
        select(EmailLog)
        .where(
            func.lower(EmailLog.recipient_email) == recipient.strip().lower(),
            EmailLog.status == EmailStatus.SENT.value,
            EmailLog.sent_at >= cutoff,
        )
        .order_by(EmailLog.sent_at.desc())
        .limit(1)
    )
    return result.scalars().first()


@router.post("/send", response_model=EmailLogResponse)
async def send_email(
    request: SendEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a single email to a recipient from a post."""
    # Verify post exists
    post = await db.get(LinkedInPost, request.post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not request.force:
        previous = await _last_sent_to(db, request.recipient_email)
        if previous:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Already emailed {request.recipient_email} on "
                    f"{previous.sent_at:%Y-%m-%d} (cooldown: "
                    f"{settings.email_cooldown_days} days). "
                    "Send again with force=true to override."
                ),
            )

    # Create email log
    email_log = EmailLog(
        post_id=request.post_id,
        recipient_email=request.recipient_email,
        subject=request.subject,
        body=request.body,
        has_resume=1 if request.attach_resume else 0,
        status=EmailStatus.PENDING.value,
    )
    db.add(email_log)
    await db.commit()
    await db.refresh(email_log)

    # Send the email
    result = email_sender.send_email(
        recipient=request.recipient_email,
        subject=request.subject,
        body=request.body,
        attach_resume=request.attach_resume,
    )

    # Update status
    if result["success"]:
        email_log.status = EmailStatus.SENT.value
    else:
        email_log.status = EmailStatus.FAILED.value
        email_log.error_message = result["error"]

    email_log.sent_at = datetime.utcnow()
    await db.commit()
    await db.refresh(email_log)

    return EmailLogResponse.model_validate(email_log)


async def _sent_in_last_day(db: AsyncSession) -> int:
    """How many emails went out in the trailing 24h, for the daily cap."""
    since = datetime.utcnow() - timedelta(days=1)
    result = await db.execute(
        select(func.count(EmailLog.id)).where(
            EmailLog.status == EmailStatus.SENT.value,
            EmailLog.sent_at >= since,
        )
    )
    return result.scalar() or 0


async def _run_bulk_job(job_id: int, request: BulkSendEmailRequest, db_url: str):
    """Background worker for a bulk send.

    Paced by settings.email_rate_limit and stopped by settings.email_daily_limit,
    so a large batch cannot burst past what Gmail tolerates.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AS
    from sqlalchemy.orm import sessionmaker as sm

    bg_engine = create_async_engine(db_url, echo=False)
    BgSession = sm(bg_engine, class_=AS, expire_on_commit=False)

    # Seconds to wait between messages to honour the per-minute limit.
    interval = 60.0 / settings.email_rate_limit if settings.email_rate_limit > 0 else 0.0

    async with BgSession() as session:
        job = await session.get(EmailJob, job_id)
        errors: list[str] = []
        skips: list[str] = []
        contacted: set[str] = set()
        sent = failed = skipped = 0
        first = True

        try:
            quota_used = await _sent_in_last_day(session)

            for post_id in request.post_ids:
                post = await session.get(LinkedInPost, post_id)
                if not post or not post.extracted_emails:
                    continue

                for recipient in [e.strip() for e in post.extracted_emails.split(",") if e.strip()]:
                    key = recipient.lower()

                    if not request.force:
                        if key in contacted:
                            skipped += 1
                            skips.append(f"{recipient}: duplicate in this batch")
                            continue
                        previous = await _last_sent_to(session, recipient)
                        if previous:
                            skipped += 1
                            skips.append(f"{recipient}: already emailed {previous.sent_at:%Y-%m-%d}")
                            continue

                    if settings.email_daily_limit and quota_used >= settings.email_daily_limit:
                        skipped += 1
                        skips.append(
                            f"{recipient}: daily limit of {settings.email_daily_limit} reached"
                        )
                        continue

                    contacted.add(key)

                    # Pace the sends. Skipped recipients cost nothing, so the wait
                    # only happens between messages actually put on the wire.
                    if not first and interval:
                        await asyncio.sleep(interval)
                    first = False

                    email_log = EmailLog(
                        post_id=post_id,
                        recipient_email=recipient,
                        subject=request.subject,
                        body=request.body,
                        has_resume=1 if request.attach_resume else 0,
                        status=EmailStatus.PENDING.value,
                    )
                    session.add(email_log)
                    await session.commit()
                    await session.refresh(email_log)

                    # Blocking SMTP call — keep it off the event loop so progress
                    # polling stays responsive while a message is in flight.
                    result = await asyncio.to_thread(
                        email_sender.send_email,
                        recipient=recipient,
                        subject=request.subject,
                        body=request.body,
                        attach_resume=request.attach_resume,
                    )

                    if result["success"]:
                        email_log.status = EmailStatus.SENT.value
                        sent += 1
                        quota_used += 1
                    else:
                        email_log.status = EmailStatus.FAILED.value
                        email_log.error_message = result["error"]
                        failed += 1
                        errors.append(f"{recipient}: {result['error']}")

                    email_log.sent_at = datetime.utcnow()

                    job = await session.get(EmailJob, job_id)
                    job.sent, job.failed, job.skipped = sent, failed, skipped
                    await session.commit()

            job = await session.get(EmailJob, job_id)
            job.status = "completed"
            job.sent, job.failed, job.skipped = sent, failed, skipped
            job.detail = json.dumps({"errors": errors, "skipped_recipients": skips})
            job.completed_at = datetime.utcnow()
            await session.commit()
            logger.info(
                f"Bulk job {job_id} completed: {sent} sent, {failed} failed, {skipped} skipped"
            )

        except Exception as e:
            logger.error(f"Bulk job {job_id} failed: {e}")
            job = await session.get(EmailJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.sent, job.failed, job.skipped = sent, failed, skipped
                job.detail = json.dumps({"errors": errors, "skipped_recipients": skips})
                job.completed_at = datetime.utcnow()
                await session.commit()
        finally:
            await bg_engine.dispose()


@router.post("/send-bulk", response_model=EmailJobResponse)
async def send_bulk_emails(
    request: BulkSendEmailRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Queue a bulk send and return immediately.

    Rate limiting means a batch takes minutes, so the work runs in the background
    and the client polls /api/emails/jobs/{id} for progress.
    """
    # Count recipients up front so the UI can show a denominator.
    total = 0
    for post_id in request.post_ids:
        post = await db.get(LinkedInPost, post_id)
        if post and post.extracted_emails:
            total += len([e for e in post.extracted_emails.split(",") if e.strip()])

    if total == 0:
        raise HTTPException(
            status_code=400,
            detail="None of the selected posts have an extracted email address.",
        )

    job = EmailJob(subject=request.subject, status="running", total_recipients=total)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(_run_bulk_job, job.id, request, settings.database_url)
    return EmailJobResponse.model_validate(job)


@router.post("/draft", response_model=DraftEmailResponse)
async def draft_email(request: DraftEmailRequest, db: AsyncSession = Depends(get_db)):
    """Draft an application email tailored to one post, using Mistral."""
    post = await db.get(LinkedInPost, request.post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not ai_extractor.available:
        raise HTTPException(
            status_code=503,
            detail=f"AI drafting unavailable: {ai_extractor.status}. "
                   "Set MISTRAL_API_KEY in backend/.env and restart.",
        )

    candidate = settings.candidate_summary or ""
    if settings.candidate_name:
        candidate = f"Name: {settings.candidate_name}\n{candidate}"
    if post.extracted_roles:
        candidate += f"\nApplying for: {post.extracted_roles}"

    drafted = await ai_extractor.draft_email(post.content, candidate.strip())
    if not drafted:
        raise HTTPException(
            status_code=502,
            detail="Mistral did not return a draft. Check the backend log and try again.",
        )

    body = drafted.body_html
    if settings.candidate_name and settings.candidate_name not in body:
        body += f"\n<p>Best regards,<br/>{settings.candidate_name}</p>"

    return DraftEmailResponse(subject=drafted.subject, body=body)


def split_name(full: str | None) -> tuple[str, str]:
    """Split a LinkedIn display name into first/last for the CSV.

    Names are messy ("Roli Verma", "SONAKSHI DHUSIA", "Priya K.", "TechCombo").
    Everything after the first token becomes the surname; a single token yields
    an empty surname rather than a guess.
    """
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _contacts_query(
    q: str | None,
    uncontacted_only: bool,
    date_from: datetime | None,
    date_to: datetime | None,
    has_company: bool,
):
    """Shared filter set for the contacts list and its CSV export."""
    stmt = select(ExtractedEmail).order_by(ExtractedEmail.last_seen_at.desc())
    if uncontacted_only:
        sent = select(func.lower(EmailLog.recipient_email)).where(
            EmailLog.status == EmailStatus.SENT.value
        )
        stmt = stmt.where(~ExtractedEmail.email.in_(sent))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(ExtractedEmail.email).like(like)
            | func.lower(func.coalesce(ExtractedEmail.author_name, "")).like(like)
            | func.lower(func.coalesce(ExtractedEmail.company, "")).like(like)
            | func.lower(func.coalesce(ExtractedEmail.role, "")).like(like)
        )
    # Filter on when we last saw the address — that is what "latest" means here.
    if date_from:
        stmt = stmt.where(ExtractedEmail.last_seen_at >= date_from)
    if date_to:
        stmt = stmt.where(ExtractedEmail.last_seen_at <= date_to)
    if has_company:
        stmt = stmt.where(
            ExtractedEmail.company.isnot(None), ExtractedEmail.company != ""
        )
    return stmt


@router.get("/contacts", response_model=list[ContactResponse])
async def list_contacts(
    limit: int = Query(500, le=5000),
    offset: int = 0,
    q: str = Query(None, description="Match email, name, company or role"),
    uncontacted_only: bool = Query(False, description="Hide addresses already emailed"),
    date_from: datetime = Query(None, description="Seen on/after this date"),
    date_to: datetime = Query(None, description="Seen on/before this date"),
    has_company: bool = Query(False, description="Only rows with a company"),
    db: AsyncSession = Depends(get_db),
):
    """Every distinct email collected — one row per address, never duplicated."""
    stmt = _contacts_query(q, uncontacted_only, date_from, date_to, has_company)
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [ContactResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/contacts/export.csv")
async def export_contacts_csv(
    q: str = Query(None),
    uncontacted_only: bool = Query(False),
    date_from: datetime = Query(None),
    date_to: datetime = Query(None),
    has_company: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Download the filtered contacts as CSV.

    Columns are fixed: email, first_name, last_name, company, designation.
    """
    stmt = _contacts_query(q, uncontacted_only, date_from, date_to, has_company)
    rows = (await db.execute(stmt)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "first_name", "last_name", "company", "designation"])
    for c in rows:
        first, last = split_name(c.author_name)
        # `role` holds comma-separated titles; the first is the primary one, and
        # keeping them all would break the CSV column for spreadsheet users.
        designation = (c.role or "").split(",")[0].strip()
        writer.writerow([c.email, first, last, c.company or "", designation])

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="contacts_{stamp}.csv"'
        },
    )


@router.get("/contacts/count")
async def contacts_count(db: AsyncSession = Depends(get_db)):
    """Totals for the dashboard: unique addresses, and how many are untouched."""
    total = (await db.execute(select(func.count(ExtractedEmail.id)))).scalar() or 0
    sent = select(func.lower(EmailLog.recipient_email)).where(
        EmailLog.status == EmailStatus.SENT.value
    )
    uncontacted = (await db.execute(
        select(func.count(ExtractedEmail.id)).where(~ExtractedEmail.email.in_(sent))
    )).scalar() or 0
    return {"unique_emails": total, "uncontacted": uncontacted}


@router.get("/jobs", response_model=list[EmailJobResponse])
async def list_email_jobs(db: AsyncSession = Depends(get_db)):
    """Recent bulk send jobs."""
    result = await db.execute(
        select(EmailJob).order_by(EmailJob.started_at.desc()).limit(20)
    )
    return [EmailJobResponse.model_validate(j) for j in result.scalars().all()]


@router.get("/jobs/{job_id}", response_model=EmailJobResponse)
async def get_email_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Progress for a single bulk send job."""
    job = await db.get(EmailJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Email job not found")
    return EmailJobResponse.model_validate(job)


@router.get("/history", response_model=list[EmailLogResponse])
async def email_history(
    status: str = Query(None, description="Filter by status: pending, sent, failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get email sending history."""
    query = select(EmailLog).order_by(EmailLog.sent_at.desc())

    if status:
        query = query.where(EmailLog.status == status)

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    logs = result.scalars().all()
    return [EmailLogResponse.model_validate(l) for l in logs]


@router.get("/stats")
async def email_stats(db: AsyncSession = Depends(get_db)):
    """Get email sending statistics."""
    total = await db.execute(select(func.count(EmailLog.id)))
    sent = await db.execute(
        select(func.count(EmailLog.id)).where(EmailLog.status == EmailStatus.SENT.value)
    )
    failed = await db.execute(
        select(func.count(EmailLog.id)).where(EmailLog.status == EmailStatus.FAILED.value)
    )

    return {
        "total": total.scalar(),
        "sent": sent.scalar(),
        "failed": failed.scalar(),
    }


@router.post("/resend/{email_id}", response_model=EmailLogResponse)
async def resend_email(email_id: int, db: AsyncSession = Depends(get_db)):
    """Resend a failed email."""
    email_log = await db.get(EmailLog, email_id)
    if not email_log:
        raise HTTPException(status_code=404, detail="Email log not found")

    result = email_sender.send_email(
        recipient=email_log.recipient_email,
        subject=email_log.subject,
        body=email_log.body,
        attach_resume=bool(email_log.has_resume),
    )

    if result["success"]:
        email_log.status = EmailStatus.SENT.value
        email_log.error_message = None
    else:
        email_log.status = EmailStatus.FAILED.value
        email_log.error_message = result["error"]

    email_log.sent_at = datetime.utcnow()
    await db.commit()
    await db.refresh(email_log)

    return EmailLogResponse.model_validate(email_log)
