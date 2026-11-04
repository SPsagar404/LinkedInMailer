import hashlib
import re
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from database import Base
import enum


def make_content_hash(content: str, author: str | None = None) -> str:
    """Stable identity for a scraped post, used to skip re-inserting duplicates.

    LinkedIn's current search UI exposes no post permalink, so post_url is always
    NULL and cannot serve as a natural key. We hash the normalised post body plus
    the author instead: the same recruiter posting the same text is the same post,
    even if it resurfaces in a later search.
    """
    body = re.sub(r"\s+", " ", (content or "")).strip().lower()
    who = (author or "").strip().lower()
    return hashlib.sha256(f"{who}\x00{body}".encode("utf-8")).hexdigest()


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ScrapeJob(Base):
    """Tracks each scraping session."""
    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_query = Column(String(500), nullable=False)
    status = Column(String(50), default="running")  # running, completed, failed
    total_posts = Column(Integer, default=0)
    total_emails_found = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    posts = relationship("LinkedInPost", back_populates="scrape_job", cascade="all, delete-orphan")


class LinkedInPost(Base):
    """A scraped LinkedIn post."""
    __tablename__ = "linkedin_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scrape_job_id = Column(Integer, ForeignKey("scrape_jobs.id"), nullable=False)
    author_name = Column(String(200), nullable=True)
    author_headline = Column(String(500), nullable=True)
    author_profile_url = Column(String(1000), nullable=True)
    content = Column(Text, nullable=False)
    post_url = Column(String(1000), nullable=True)
    # Dedupe key — see make_content_hash(). Indexed but not UNIQUE: databases
    # created before this column may already hold duplicates, and a unique index
    # would refuse to build on them rather than silently discarding rows.
    content_hash = Column(String(64), nullable=True, index=True)
    # LinkedIn only ever shows a relative age ("5h", "4d"), never a real date.
    # posted_ago keeps what was displayed; posted_at is derived from it and is
    # therefore approximate — good to the precision LinkedIn showed.
    posted_ago = Column(String(20), nullable=True)
    posted_at = Column(DateTime, nullable=True, index=True)

    # Extracted data
    extracted_emails = Column(Text, nullable=True)       # comma-separated emails
    extracted_roles = Column(Text, nullable=True)         # comma-separated roles
    extracted_experience = Column(String(200), nullable=True)
    extracted_company = Column(String(200), nullable=True)
    extracted_location = Column(Text, nullable=True)      # comma-separated locations

    scraped_at = Column(DateTime, default=datetime.utcnow)

    scrape_job = relationship("ScrapeJob", back_populates="posts")
    email_logs = relationship("EmailLog", back_populates="post", cascade="all, delete-orphan")


class ExtractedEmail(Base):
    """One row per distinct email address ever collected.

    Post-level dedup (content_hash) does not prevent the same recruiter address
    appearing in dozens of different posts. This table is the canonical contact
    list: `email` is UNIQUE, so an address seen 20 times is stored once, with a
    counter and a link back to the post it first came from.
    """
    __tablename__ = "extracted_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    first_post_id = Column(Integer, ForeignKey("linkedin_posts.id"), nullable=True)
    times_seen = Column(Integer, default=1)
    author_name = Column(String(200), nullable=True)
    company = Column(String(200), nullable=True)
    role = Column(String(500), nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)


class EmailJob(Base):
    """Tracks a bulk send running in the background.

    Bulk sends are paced by the rate limiter, so a run of any size takes minutes.
    It cannot live inside the HTTP request — the job row is what the dashboard
    polls for progress.
    """
    __tablename__ = "email_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject = Column(String(500), nullable=False)
    status = Column(String(50), default="running")  # running, completed, failed
    total_recipients = Column(Integer, default=0)
    sent = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    detail = Column(Text, nullable=True)          # JSON: errors + skip reasons
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class EmailLog(Base):
    """Log of sent emails."""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("linkedin_posts.id"), nullable=False)
    recipient_email = Column(String(300), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    has_resume = Column(Integer, default=0)  # 0 or 1
    status = Column(String(50), default=EmailStatus.PENDING.value)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("LinkedInPost", back_populates="email_logs")
