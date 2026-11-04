from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Scrape Schemas ──────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    search_query: str
    max_posts: int = 10
    # Relative window LinkedIn itself filters on: past-24h | past-week | past-month.
    date_posted: Optional[str] = None
    # sortBy="date_posted" — newest first. This is what surfaces minutes-old posts.
    sort_by_latest: bool = True
    # Wanted experience range, in years (e.g. 2-5). A post is kept when its
    # stated requirement OVERLAPS this range; posts stating nothing are kept.
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    # Exact range, applied to each post's approximate date. LinkedIn has no
    # from/to filter, so this is derived from the age shown on the card.
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    # Extra literal search terms run alongside the expanded title, e.g.
    # "java developer 3+". They are searched first, before the generated ones.
    extra_queries: Optional[list[str]] = None
    # Keep only posts whose role/content mentions one of these terms. This is
    # the relevance gate: the experience filter says "how senior", this says
    # "is it even the right field". None disables it.
    role_keywords: Optional[list[str]] = None
    # Keep only posts naming one of these places. LinkedIn's content search
    # has no location facet, so the city is read back out of the post text.
    location_keywords: Optional[list[str]] = None
    # Floor on new (never-seen) email addresses. None uses the configured
    # default; 0 disables the floor and stops purely on the post target.
    min_new_emails: Optional[int] = None


class ScrapeJobResponse(BaseModel):
    id: int
    search_query: str
    status: str
    total_posts: int
    total_emails_found: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


# ── Post Schemas ────────────────────────────────────────────────
class PostResponse(BaseModel):
    id: int
    scrape_job_id: int
    author_name: Optional[str] = None
    author_headline: Optional[str] = None
    author_profile_url: Optional[str] = None
    content: str
    post_url: Optional[str] = None
    extracted_emails: Optional[str] = None
    extracted_roles: Optional[str] = None
    extracted_experience: Optional[str] = None
    extracted_location: Optional[str] = None
    posted_ago: Optional[str] = None
    posted_at: Optional[datetime] = None
    scraped_at: datetime

    class Config:
        from_attributes = True


# ── Email Schemas ───────────────────────────────────────────────
class SendEmailRequest(BaseModel):
    post_id: int
    recipient_email: str
    subject: str
    body: str
    attach_resume: bool = False
    # Set true to email an address again inside the cooldown window.
    force: bool = False


class BulkSendEmailRequest(BaseModel):
    post_ids: list[int]
    subject: str
    body: str
    attach_resume: bool = False
    force: bool = False


class EmailLogResponse(BaseModel):
    id: int
    post_id: int
    recipient_email: str
    subject: str
    body: str
    has_resume: int
    status: str
    error_message: Optional[str] = None
    sent_at: datetime

    class Config:
        from_attributes = True


class DraftEmailRequest(BaseModel):
    post_id: int


class DraftEmailResponse(BaseModel):
    subject: str
    body: str


class EmailJobResponse(BaseModel):
    id: int
    subject: str
    status: str
    total_recipients: int
    sent: int
    failed: int
    skipped: int
    detail: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContactResponse(BaseModel):
    id: int
    email: str
    times_seen: int
    author_name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    first_post_id: Optional[int] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Resume Schema ───────────────────────────────────────────────
class ResumeInfoResponse(BaseModel):
    exists: bool
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_at: Optional[str] = None
    max_size_mb: int


# ── Stats Schema ────────────────────────────────────────────────
class DashboardStats(BaseModel):
    total_posts_scraped: int
    total_emails_found: int
    total_emails_sent: int
    total_emails_failed: int
    recent_scrape_jobs: list[ScrapeJobResponse]
