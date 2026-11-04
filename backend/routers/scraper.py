"""
Scraper API routes.
Handles LinkedIn scraping jobs.
"""
import re
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import ScrapeJob, LinkedInPost, ExtractedEmail, make_content_hash
from schemas import ScrapeRequest, ScrapeJobResponse
from services.linkedin_scraper import LinkedInScraper

router = APIRouter(prefix="/api/scrape", tags=["Scraper"])


_YEARS_RE = re.compile(r"(\d+)\s*(?:-|to|–)\s*(\d+)|(\d+)\s*\+|\b(\d+)\b")


def _parse_experience(stated: str | None) -> tuple[int, int] | None:
    """Parse a post's stated requirement into (min_years, max_years).

    Handles "4-6 years", "3+ years", "5 years", "0-5 Years". Returns None when
    the post states nothing parseable.
    """
    if not stated:
        return None
    t = stated.lower()
    m = re.search(r"(\d+)\s*(?:-|to|–|—)\s*(\d+)", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(\d+)\s*\+", t)
    if m:
        return (int(m.group(1)), 99)
    m = re.search(r"(\d+)", t)
    if m:
        return (int(m.group(1)), int(m.group(1)))
    return None


def _experience_matches(stated: str | None, want_min: int | None, want_max: int | None) -> bool:
    """Does a post's stated requirement overlap the wanted range?

    Overlap, not containment: a post asking 3-7 years is relevant to someone
    targeting 2-5. Posts stating nothing are kept — an unstated requirement is
    not a mismatch, and dropping them would discard most results.
    """
    if want_min is None and want_max is None:
        return True
    span = _parse_experience(stated)
    if span is None:
        return True
    lo, hi = span
    if want_min is not None and hi < want_min:
        return False
    if want_max is not None and lo > want_max:
        return False
    return True


def _any_keyword(haystack: str, keywords: list[str] | None) -> bool:
    """Does any keyword appear in `haystack` as a whole word?

    Word boundaries matter more than they look: a plain substring test for
    "ai" hits "email", "available" and "training", which appear in nearly
    every hiring post, so the gate would pass everything.
    """
    if not keywords:
        return True
    for kw in keywords:
        kw = (kw or "").strip().lower()
        if not kw:
            continue
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", haystack):
            return True
    return False


def _location_matches(post: dict, keywords: list[str] | None) -> bool:
    """Is this post for one of the places we care about?

    LinkedIn's content search has no location facet, so the city has to be
    read back out of the post itself. Matched against the extracted location
    and the body, since most hiring posts name the city in the text rather
    than in any structured field.
    """
    if not keywords:
        return True
    haystack = " ".join(filter(None, [
        post.get("extracted_location") or "",
        post.get("content") or "",
        post.get("author_headline") or "",
    ])).lower()
    return _any_keyword(haystack, keywords)


def _role_matches(post: dict, keywords: list[str] | None) -> bool:
    """Does this post actually concern the field we searched for?

    The experience filter answers "how senior"; this answers "is it even the
    right field". Without it an "AI/ML fresher" search returns every generic
    "fresher hiring" post, because those posts shout FRESHER and HIRING far
    louder than they mention machine learning.

    Matched against the extracted role AND the post body: the role field is
    often generic ("Fresher") while the body names the stack. Word boundaries
    are required, so the keyword "ai" matches "AI/ML" but not "email",
    "available" or "train".
    """
    if not keywords:
        return True
    haystack = " ".join(filter(None, [
        post.get("extracted_roles") or "",
        post.get("content") or "",
        post.get("author_headline") or "",
    ])).lower()
    return _any_keyword(haystack, keywords)


async def _record_email(session, addr, post_id, author, roles, company=None):
    """Upsert one address into the unique-contact table.

    Called for every scraped post, including ones skipped as duplicate posts:
    the post may be a repeat while the address is still new to us, and the
    address is the thing worth keeping.
    """
    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        return False
    existing = (await session.execute(
        select(ExtractedEmail).where(ExtractedEmail.email == addr)
    )).scalars().first()
    if existing:
        existing.times_seen += 1
        existing.last_seen_at = datetime.utcnow()
        # Backfill details a later sighting supplied but an earlier one lacked.
        existing.company = existing.company or company
        existing.author_name = existing.author_name or author
        existing.role = existing.role or roles
        return False
    session.add(ExtractedEmail(
        email=addr, first_post_id=post_id, times_seen=1,
        author_name=author, role=roles, company=company,
    ))
    return True


async def _run_scrape_job(
    job_id: int,
    search_query: str,
    max_posts: int,
    db_url: str,
    date_posted: str | None = None,
    sort_by_latest: bool = True,
    experience_min: int | None = None,
    experience_max: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_new_emails: int | None = None,
    extra_queries: list | None = None,
    role_keywords: list | None = None,
    location_keywords: list | None = None,
):
    """Background task to run LinkedIn scraping."""
    import logging
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AS
    from sqlalchemy.orm import sessionmaker as sm

    logger = logging.getLogger("ScrapeJob")

    # Create a new engine/session for the background task
    bg_engine = create_async_engine(db_url, echo=False)
    BgSession = sm(bg_engine, class_=AS, expire_on_commit=False)

    async with BgSession() as session:
        try:
            scraper = LinkedInScraper()

            # Addresses already collected. The scraper needs these to tell a
            # genuinely new contact from one it has re-found.
            known_emails = set((await session.execute(
                select(ExtractedEmail.email)
            )).scalars().all())
            floor = (settings.min_new_emails_per_run
                     if min_new_emails is None else min_new_emails)
            logger.info(
                f"Scrape job {job_id}: {len(known_emails)} emails already known, "
                f"floor = {floor} new"
            )

            async def _progress(found, qi, qtotal, new_emails=0):
                job = await session.get(ScrapeJob, job_id)
                if job:
                    job.total_posts = found
                    job.total_emails_found = new_emails
                    await session.commit()

            # One LinkedIn query returns at most ~12 results, so any sizeable
            # target has to come from many query variants merged together.
            posts = await scraper.scrape_many(
                search_query, target_posts=max_posts,
                date_posted=date_posted, sort_by_latest=sort_by_latest,
                progress=_progress,
                min_new_emails=floor, known_emails=known_emails,
                extra_queries=extra_queries,
            )

            # Filters LinkedIn cannot apply itself.
            scraped_count = len(posts)
            if experience_min is not None or experience_max is not None:
                posts = [
                    p for p in posts
                    if _experience_matches(
                        p.get("extracted_experience"), experience_min, experience_max
                    )
                ]
            if role_keywords:
                before = len(posts)
                posts = [p for p in posts if _role_matches(p, role_keywords)]
                logger.info(
                    f"Relevance gate kept {len(posts)}/{before} posts "
                    f"(keywords={role_keywords})"
                )
            if location_keywords:
                before = len(posts)
                posts = [p for p in posts if _location_matches(p, location_keywords)]
                logger.info(
                    f"Location gate kept {len(posts)}/{before} posts "
                    f"(keywords={location_keywords})"
                )
            if date_from or date_to:
                kept = []
                for p in posts:
                    when = p.get("posted_at")
                    if when is None:
                        continue  # no date shown — cannot honour an exact range
                    if date_from and when < date_from:
                        continue
                    if date_to and when > date_to:
                        continue
                    kept.append(p)
                posts = kept
            if len(posts) != scraped_count:
                logger.info(
                    f"Filters kept {len(posts)}/{scraped_count} posts "
                    f"(experience={experience_min}-{experience_max}, from={date_from}, to={date_to})"
                )

            # Skip posts we already have. The same hiring post resurfaces across
            # searches and re-runs, and post_url is always NULL on LinkedIn's
            # current UI, so identity comes from a content hash instead.
            hashes = {
                id(p): make_content_hash(
                    p.get("content", ""),
                    p.get("author_profile_url") or p.get("author_name"),
                )
                for p in posts
            }
            existing = set()
            if hashes:
                existing = set((await session.execute(
                    select(LinkedInPost.content_hash).where(
                        LinkedInPost.content_hash.in_(list(hashes.values()))
                    )
                )).scalars().all())

            total_emails = 0
            new_email_count = 0
            inserted = 0
            skipped = 0
            seen_in_batch = set()
            for post_data in posts:
                content_hash = hashes[id(post_data)]
                if content_hash in existing or content_hash in seen_in_batch:
                    skipped += 1
                    # The post is a repeat, but its addresses may not be.
                    for raw in (post_data.get("extracted_emails") or "").split(","):
                        await _record_email(
                            session, raw, None,
                            post_data.get("author_name"),
                            post_data.get("extracted_roles"),
                            post_data.get("extracted_company"),
                        )
                    continue
                seen_in_batch.add(content_hash)

                db_post = LinkedInPost(
                    scrape_job_id=job_id,
                    author_name=post_data.get("author_name"),
                    author_headline=post_data.get("author_headline"),
                    author_profile_url=post_data.get("author_profile_url"),
                    content=post_data.get("content", ""),
                    post_url=post_data.get("post_url"),
                    content_hash=content_hash,
                    posted_ago=post_data.get("posted_ago"),
                    posted_at=post_data.get("posted_at"),
                    extracted_emails=post_data.get("extracted_emails"),
                    extracted_roles=post_data.get("extracted_roles"),
                    extracted_experience=post_data.get("extracted_experience"),
                    extracted_location=post_data.get("extracted_location"),
                    extracted_company=post_data.get("extracted_company"),
                )
                session.add(db_post)
                inserted += 1

                if post_data.get("extracted_emails"):
                    total_emails += len(post_data["extracted_emails"].split(","))
                    await session.flush()   # need db_post.id for first_post_id
                    for raw in post_data["extracted_emails"].split(","):
                        if await _record_email(
                            session, raw, db_post.id,
                            post_data.get("author_name"),
                            post_data.get("extracted_roles"),
                            post_data.get("extracted_company"),
                        ):
                            new_email_count += 1

            # Update scrape job status. total_posts counts what was actually
            # stored, so the dashboard stays consistent with the posts table.
            job = await session.get(ScrapeJob, job_id)
            if job:
                job.status = "completed"
                job.total_posts = inserted
                # Count the addresses that were genuinely new — that is the
                # number the daily floor is expressed in.
                job.total_emails_found = new_email_count
                job.completed_at = datetime.utcnow()

            await session.commit()
            logger.info(
                f"Scrape job {job_id} completed: {inserted} new posts "
                f"({skipped} duplicate posts of {len(posts)} scraped), "
                f"{new_email_count} new emails ({total_emails} mentions)"
            )

        except Exception as e:
            logger.error(f"Scrape job {job_id} failed: {e}")
            job = await session.get(ScrapeJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
            await session.commit()
        finally:
            await bg_engine.dispose()


@router.post("/start", response_model=ScrapeJobResponse)
async def start_scrape(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start a new LinkedIn scraping job."""
    # Create scrape job record
    job = ScrapeJob(
        search_query=request.search_query,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Launch scraping in background
    from config import settings
    background_tasks.add_task(
        _run_scrape_job,
        job.id,
        request.search_query,
        request.max_posts,
        settings.database_url,
        request.date_posted,
        request.sort_by_latest,
        request.experience_min,
        request.experience_max,
        request.date_from,
        request.date_to,
        request.min_new_emails,
        request.extra_queries,
        request.role_keywords,
        request.location_keywords,
    )

    return ScrapeJobResponse.model_validate(job)


@router.get("/jobs", response_model=list[ScrapeJobResponse])
async def list_scrape_jobs(db: AsyncSession = Depends(get_db)):
    """List all scrape jobs."""
    result = await db.execute(
        select(ScrapeJob).order_by(ScrapeJob.started_at.desc()).limit(50)
    )
    jobs = result.scalars().all()
    return [ScrapeJobResponse.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=ScrapeJobResponse)
async def get_scrape_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific scrape job status."""
    job = await db.get(ScrapeJob, job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return ScrapeJobResponse.model_validate(job)
