"""
LinkedIn Post Scraper & Auto-Email — FastAPI Backend
Main application entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func

from database import init_db, get_db, async_session
from models import LinkedInPost, EmailLog, ScrapeJob, EmailStatus
from schemas import DashboardStats, ScrapeJobResponse
from routers import scraper, posts, emails, resume, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("App")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting LinkedIn Mailer API...")
    await init_db()
    logger.info("Database initialized.")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="LinkedIn Post Scraper & Auto-Email",
    description="Scrape LinkedIn posts, extract emails, and send automated emails.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Mount routers
app.include_router(scraper.router)
app.include_router(posts.router)
app.include_router(emails.router)
app.include_router(resume.router)
app.include_router(health.router)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "LinkedIn Post Scraper & Auto-Email API"}


@app.get("/api/stats", response_model=DashboardStats)
async def dashboard_stats():
    """Get dashboard overview statistics."""
    async with async_session() as db:
        # Total posts
        total_posts_result = await db.execute(select(func.count(LinkedInPost.id)))
        total_posts = total_posts_result.scalar() or 0

        # Posts with emails
        emails_found_result = await db.execute(
            select(func.count(LinkedInPost.id)).where(
                LinkedInPost.extracted_emails.isnot(None),
                LinkedInPost.extracted_emails != "",
            )
        )
        total_emails_found = emails_found_result.scalar() or 0

        # Emails sent
        sent_result = await db.execute(
            select(func.count(EmailLog.id)).where(EmailLog.status == EmailStatus.SENT.value)
        )
        total_sent = sent_result.scalar() or 0

        # Emails failed
        failed_result = await db.execute(
            select(func.count(EmailLog.id)).where(EmailLog.status == EmailStatus.FAILED.value)
        )
        total_failed = failed_result.scalar() or 0

        # Recent scrape jobs
        jobs_result = await db.execute(
            select(ScrapeJob).order_by(ScrapeJob.started_at.desc()).limit(10)
        )
        recent_jobs = [
            ScrapeJobResponse.model_validate(j) for j in jobs_result.scalars().all()
        ]

        return DashboardStats(
            total_posts_scraped=total_posts,
            total_emails_found=total_emails_found,
            total_emails_sent=total_sent,
            total_emails_failed=total_failed,
            recent_scrape_jobs=recent_jobs,
        )


if __name__ == "__main__":
    import uvicorn
    # NOTE: reload=True is incompatible with Playwright on Windows — uvicorn switches
    # to WindowsSelectorEventLoopPolicy when it needs a subprocess, and that loop
    # cannot spawn Chromium (NotImplementedError). Keep reload off here.
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
