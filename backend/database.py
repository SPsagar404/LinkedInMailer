import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings

logger = logging.getLogger("Database")

engine = create_async_engine(settings.database_url, echo=False)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def _migrate_content_hash(conn):
    """Add linkedin_posts.content_hash to databases created before it existed.

    create_all() only creates missing *tables*, never missing columns, so an
    existing linkedin_mailer.db needs the column added and backfilled by hand.
    Idempotent: safe to run on every startup.
    """
    if engine.dialect.name != "sqlite":
        return

    cols = await conn.execute(text("PRAGMA table_info(linkedin_posts)"))
    names = {row[1] for row in cols}
    if not names:
        return  # table not created yet — create_all will include the column
    if "content_hash" not in names:
        logger.info("Migrating: adding linkedin_posts.content_hash")
        await conn.execute(text("ALTER TABLE linkedin_posts ADD COLUMN content_hash VARCHAR(64)"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_linkedin_posts_content_hash "
            "ON linkedin_posts (content_hash)"
        ))

    # Backfill any rows still missing a hash (new column, or rows predating it).
    from models import make_content_hash

    rows = (await conn.execute(text(
        "SELECT id, content, author_profile_url, author_name FROM linkedin_posts "
        "WHERE content_hash IS NULL"
    ))).fetchall()
    if rows:
        logger.info(f"Migrating: backfilling content_hash for {len(rows)} posts")
        for pid, content, profile_url, author_name in rows:
            h = make_content_hash(content, profile_url or author_name)
            await conn.execute(
                text("UPDATE linkedin_posts SET content_hash = :h WHERE id = :i"),
                {"h": h, "i": pid},
            )

        dupes = (await conn.execute(text(
            "SELECT COUNT(*) FROM (SELECT content_hash FROM linkedin_posts "
            "GROUP BY content_hash HAVING COUNT(*) > 1)"
        ))).scalar()
        if dupes:
            logger.warning(
                f"{dupes} duplicate post group(s) already exist in the database. "
                "They are left untouched; future scrapes will not add more."
            )


async def _migrate_posted_at(conn):
    """Add linkedin_posts.posted_ago / posted_at to pre-existing databases."""
    if engine.dialect.name != "sqlite":
        return
    cols = await conn.execute(text("PRAGMA table_info(linkedin_posts)"))
    names = {row[1] for row in cols}
    if not names:
        return
    for col, ddl in (
        ("posted_ago", "ALTER TABLE linkedin_posts ADD COLUMN posted_ago VARCHAR(20)"),
        ("posted_at", "ALTER TABLE linkedin_posts ADD COLUMN posted_at DATETIME"),
        ("extracted_company",
         "ALTER TABLE linkedin_posts ADD COLUMN extracted_company VARCHAR(200)"),
    ):
        if col not in names:
            logger.info(f"Migrating: adding linkedin_posts.{col}")
            await conn.execute(text(ddl))
    if "posted_at" not in names:
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_linkedin_posts_posted_at "
            "ON linkedin_posts (posted_at)"
        ))


async def _backfill_extracted_emails(conn):
    """Seed extracted_emails from posts scraped before the table existed."""
    if engine.dialect.name != "sqlite":
        return
    existing = (await conn.execute(text("SELECT COUNT(*) FROM extracted_emails"))).scalar()
    if existing:
        return
    rows = (await conn.execute(text(
        "SELECT id, extracted_emails, author_name, extracted_roles FROM linkedin_posts "
        "WHERE extracted_emails IS NOT NULL AND extracted_emails != ''"
    ))).fetchall()
    seen = {}
    for pid, emails, author, roles in rows:
        for raw in (emails or "").split(","):
            addr = raw.strip().lower()
            if not addr or "@" not in addr:
                continue
            if addr in seen:
                seen[addr]["n"] += 1
            else:
                seen[addr] = {"pid": pid, "author": author, "roles": roles, "n": 1}
    for addr, d in seen.items():
        await conn.execute(
            text("INSERT OR IGNORE INTO extracted_emails "
                 "(email, first_post_id, times_seen, author_name, role, "
                 " first_seen_at, last_seen_at) "
                 "VALUES (:e, :p, :n, :a, :r, :t, :t)"),
            {"e": addr, "p": d["pid"], "n": d["n"], "a": d["author"], "r": d["roles"],
             "t": datetime.utcnow()},
        )
    if seen:
        logger.info(f"Migrating: seeded {len(seen)} unique emails from existing posts")


async def init_db():
    """Create all tables on startup."""
    # Importing models registers every table on Base.metadata. Without this,
    # create_all() silently creates nothing when init_db() is the entry point.
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_content_hash(conn)
        await _migrate_posted_at(conn)
        await _backfill_extracted_emails(conn)


async def get_db():
    """Dependency to get a database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
