"""
Posts API routes.
CRUD operations for scraped LinkedIn posts.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import LinkedInPost
from schemas import PostResponse

router = APIRouter(prefix="/api/posts", tags=["Posts"])


@router.get("/", response_model=list[PostResponse])
async def list_posts(
    scrape_job_id: int = Query(None, description="Filter by scrape job ID"),
    has_email: bool = Query(None, description="Filter posts with emails only"),
    search: str = Query(None, description="Search in post content"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List scraped posts with optional filters."""
    # Newest *published* first. posted_at is what the user means by "latest";
    # scraped_at only records when we happened to fetch it. Posts with no
    # visible date sort last rather than jumping to the top as NULLs.
    query = select(LinkedInPost).order_by(
        LinkedInPost.posted_at.desc().nullslast(),
        LinkedInPost.scraped_at.desc(),
    )

    if scrape_job_id:
        query = query.where(LinkedInPost.scrape_job_id == scrape_job_id)

    if has_email:
        query = query.where(
            LinkedInPost.extracted_emails.isnot(None),
            LinkedInPost.extracted_emails != "",
        )

    if search:
        query = query.where(LinkedInPost.content.ilike(f"%{search}%"))

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    posts = result.scalars().all()
    return [PostResponse.model_validate(p) for p in posts]


@router.get("/count")
async def count_posts(
    has_email: bool = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get total post count."""
    query = select(func.count(LinkedInPost.id))
    if has_email:
        query = query.where(
            LinkedInPost.extracted_emails.isnot(None),
            LinkedInPost.extracted_emails != "",
        )
    result = await db.execute(query)
    return {"count": result.scalar()}


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific post by ID."""
    post = await db.get(LinkedInPost, post_id)
    if not post:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Post not found")
    return PostResponse.model_validate(post)


@router.delete("/{post_id}")
async def delete_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a post."""
    post = await db.get(LinkedInPost, post_id)
    if not post:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Post not found")
    await db.delete(post)
    await db.commit()
    return {"message": "Post deleted"}
