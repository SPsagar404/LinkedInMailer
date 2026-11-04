import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # LinkedIn
    linkedin_email: str = os.getenv("LINKEDIN_EMAIL", "")
    linkedin_password: str = os.getenv("LINKEDIN_PASSWORD", "")

    # Gmail SMTP
    gmail_email: str = os.getenv("GMAIL_EMAIL", "")
    gmail_app_password: str = os.getenv("GMAIL_APP_PASSWORD", "")
    gmail_smtp_host: str = "smtp.gmail.com"
    gmail_smtp_port: int = 587

    # Mistral AI (extraction + email drafting). Everything degrades to the regex
    # extractor when the key is absent, so the app runs fine without it.
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    # Tried in order when the primary model is rate-limited or unavailable.
    mistral_fallback_models: str = os.getenv(
        "MISTRAL_FALLBACK_MODELS", "mistral-medium-latest,open-mistral-nemo"
    )
    # Requests are throttled to mistral_rpm and issued one at a time; free tiers
    # are rate-limited, and parallelism only burns the allowance faster.
    mistral_concurrency: int = int(os.getenv("MISTRAL_CONCURRENCY", "1"))
    mistral_rpm: int = int(os.getenv("MISTRAL_RPM", "30"))
    # Posts per extraction request. Batching keeps request counts low:
    # 10 posts becomes 2 requests instead of 10.
    mistral_batch_size: int = int(os.getenv("MISTRAL_BATCH_SIZE", "5"))

    # Used to personalise AI-drafted emails.
    candidate_name: str = os.getenv("CANDIDATE_NAME", "")
    candidate_summary: str = os.getenv("CANDIDATE_SUMMARY", "")

    # Minimum number of *previously unseen* email addresses a scrape run must
    # collect before it stops. A run that only re-finds known contacts adds
    # nothing, so the query loop keeps going until this many are new.
    min_new_emails_per_run: int = int(os.getenv("MIN_NEW_EMAILS_PER_RUN", "10"))

    # Database
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./linkedin_mailer.db")

    # Scraping
    # Scroll passes per search. LinkedIn loads ~6 more posts per pass; the loop
    # stops early once the list stops growing, so a higher budget costs nothing
    # on short result sets and digs deeper on long ones.
    scroll_pages_per_query: int = int(os.getenv("SCROLL_PAGES_PER_QUERY", "20"))
    scrape_delay_min: int = int(os.getenv("SCRAPE_DELAY_MIN", "3"))
    scrape_delay_max: int = int(os.getenv("SCRAPE_DELAY_MAX", "7"))

    # Email Rate Limiting — enforced in the bulk send worker.
    email_rate_limit: int = int(os.getenv("EMAIL_RATE_LIMIT", "20"))  # per minute
    # Personal Gmail allows roughly 500 messages/day; stay under it so a bulk run
    # can't get the sending account throttled or suspended. 0 disables the cap.
    email_daily_limit: int = int(os.getenv("EMAIL_DAILY_LIMIT", "400"))

    # Don't email the same address twice within this many days. 0 disables the
    # check. Guards against re-contacting a recruiter when the same hiring post
    # is scraped again under a different search.
    email_cooldown_days: int = int(os.getenv("EMAIL_COOLDOWN_DAYS", "30"))

    # Paths
    cookies_path: str = os.path.join(os.path.dirname(__file__), "linkedin_cookies.json")
    templates_path: str = os.path.join(os.path.dirname(__file__), "templates")
    resume_path: str = os.path.join(os.path.dirname(__file__), "resume.pdf")
    # Sidecar holding the uploaded resume's original filename / size / timestamp,
    # so the dashboard can show what is stored and emails can attach it under the
    # name the user uploaded rather than a generic "resume.pdf".
    resume_meta_path: str = os.path.join(os.path.dirname(__file__), "resume_meta.json")
    max_resume_mb: int = int(os.getenv("MAX_RESUME_MB", "10"))

    class Config:
        env_file = ".env"


settings = Settings()
