"""
System health routes.

Most of this app's failure modes are silent: a missing resume attaches nothing,
absent spaCy quietly degrades location extraction, expired LinkedIn cookies just
look like "0 posts". These checks surface all of it in one place.
"""
import json
import logging
import os
import smtplib
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from config import settings
from database import async_session
from models import LinkedInPost, EmailLog, EmailStatus

logger = logging.getLogger("Health")

router = APIRouter(prefix="/api/health", tags=["Health"])


def _check(name: str, ok: bool, detail: str, hint: str = "", level: str = None) -> dict:
    return {
        "name": name,
        "status": level or ("ok" if ok else "error"),
        "detail": detail,
        "hint": hint,
    }


def _check_linkedin() -> dict:
    if not os.path.exists(settings.cookies_path):
        return _check(
            "LinkedIn session", False, "No saved session cookies.",
            "Run a scrape — it will log in and save cookies.", level="warning",
        )
    try:
        with open(settings.cookies_path, encoding="utf-8") as f:
            cookies = json.load(f).get("cookies", [])
    except (json.JSONDecodeError, OSError) as e:
        return _check("LinkedIn session", False, f"Cookie file unreadable: {e}",
                      "Delete linkedin_cookies.json and scrape again to re-login.")

    has_li_at = any(c.get("name") == "li_at" for c in cookies)
    age_days = (datetime.now() - datetime.fromtimestamp(
        os.path.getmtime(settings.cookies_path))).days

    if not has_li_at:
        return _check("LinkedIn session", False,
                      f"{len(cookies)} cookies but no li_at session cookie.",
                      "Delete linkedin_cookies.json and scrape again to re-login.")
    if age_days > 25:
        return _check("LinkedIn session", False,
                      f"Session is {age_days} days old — it may have expired.",
                      "Re-run a scrape; a re-login refreshes it.", level="warning")
    return _check("LinkedIn session", True,
                  f"li_at present, {len(cookies)} cookies, {age_days} day(s) old.")


def _check_gmail(deep: bool) -> dict:
    if not settings.gmail_email or not settings.gmail_app_password:
        return _check("Gmail credentials", False, "GMAIL_EMAIL / GMAIL_APP_PASSWORD not set.",
                      "Add them to backend/.env (needs a Google App Password).")
    if not deep:
        return _check("Gmail credentials", True,
                      f"Configured for {settings.gmail_email} (not verified).",
                      "Run the deep check to confirm the App Password works.")
    try:
        with smtplib.SMTP(settings.gmail_smtp_host, settings.gmail_smtp_port, timeout=15) as s:
            s.starttls()
            s.login(settings.gmail_email, settings.gmail_app_password)
        return _check("Gmail credentials", True, f"SMTP login OK for {settings.gmail_email}.")
    except smtplib.SMTPAuthenticationError:
        return _check("Gmail credentials", False, "SMTP rejected the App Password.",
                      "Regenerate the App Password in your Google account.")
    except Exception as e:
        return _check("Gmail credentials", False, f"SMTP check failed: {e}",
                      "Check network access to smtp.gmail.com:587.")


def _check_resume() -> dict:
    if not os.path.exists(settings.resume_path):
        return _check("Resume", False, "No resume uploaded.",
                      "Upload one under Settings — emails with 'Attach resume' on "
                      "would otherwise go out with no attachment.", level="warning")
    size = os.path.getsize(settings.resume_path)
    name = "resume.pdf"
    try:
        with open(settings.resume_meta_path, encoding="utf-8") as f:
            name = json.load(f).get("original_filename", name)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _check("Resume", True, f"{name} ({size / 1024:.0f} KB)")


def _check_spacy() -> dict:
    try:
        import spacy
        spacy.load("en_core_web_sm")
        return _check("spaCy model", True, "en_core_web_sm loaded.")
    except Exception:
        return _check(
            "spaCy model", False,
            "en_core_web_sm not installed — location extraction uses regex fallback.",
            "venv\\Scripts\\python.exe -m spacy download en_core_web_sm",
            level="warning",
        )


def _check_mistral(deep: bool) -> dict:
    from services.ai_extractor import ai_extractor

    if not ai_extractor.available:
        return _check(
            "Mistral AI", False, f"Disabled — {ai_extractor.status}.",
            "Add MISTRAL_API_KEY to backend/.env and restart. Extraction falls "
            "back to regex until then.", level="warning",
        )
    if not deep:
        return _check("Mistral AI", True,
                      f"Configured, model {settings.mistral_model} (not verified).",
                      "Run the deep check to send a real test request.")
    try:
        from services.ai_extractor import ExtractedPost
        result = ai_extractor._generate(
            "Return is_hiring_post=true, roles=['Test'], everything else empty.",
            ExtractedPost, 0.0,
        )
        if result is None:
            return _check("Mistral AI", False, "API returned no parsed result.",
                          "Check the model name in MISTRAL_MODEL.")
        return _check("Mistral AI", True,
                      f"Live test OK against {settings.mistral_model}.")
    except Exception as e:
        return _check("Mistral AI", False, f"API call failed: {e}",
                      "Verify the key is valid and MISTRAL_MODEL exists.")


@router.get("/status")
async def health_status(
    deep: bool = Query(False, description="Also attempt a real Gmail SMTP login"),
):
    """Report on every dependency that can fail silently."""
    checks = [
        _check_linkedin(),
        _check_gmail(deep),
        _check_resume(),
        _check_mistral(deep),
        _check_spacy(),
    ]

    async with async_session() as db:
        try:
            posts = (await db.execute(select(func.count(LinkedInPost.id)))).scalar() or 0
            sent = (await db.execute(select(func.count(EmailLog.id)).where(
                EmailLog.status == EmailStatus.SENT.value))).scalar() or 0
            checks.append(_check("Database", True, f"{posts} posts, {sent} emails sent."))
        except Exception as e:
            checks.append(_check("Database", False, f"Query failed: {e}"))

    checks.append(_check(
        "Email limits", True,
        f"{settings.email_rate_limit}/min, {settings.email_daily_limit or 'unlimited'}/day, "
        f"{settings.email_cooldown_days}-day resend cooldown.",
    ))

    worst = "ok"
    if any(c["status"] == "error" for c in checks):
        worst = "error"
    elif any(c["status"] == "warning" for c in checks):
        worst = "warning"

    return {"overall": worst, "checks": checks}
