"""
Mistral-backed extraction and email drafting.

The regex/spaCy DataExtractor stays the fallback: it is offline, free and always
available. This layer runs on top of it and is *strictly optional* — with no
MISTRAL_API_KEY, or on any API error, callers silently get the regex result.

Provider rate limits shape the design:
  - posts are batched into one request instead of one request each,
  - all calls pass through a process-wide throttle,
  - retries honour a server-supplied Retry-After when present,
  - concurrency is 1, because parallelism only burns the allowance faster.
"""
import asyncio
import logging
import re
import threading
import time
from collections import deque
from typing import Optional

from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger("AIExtractor")

RETRY_ATTEMPTS = 2
MAX_RETRY_WAIT = 45.0   # cap on an honoured server retryDelay, seconds


def _error_code(error: Exception) -> Optional[int]:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if isinstance(code, int):
        return code
    m = re.search(r"\b(4\d\d|5\d\d)\b", str(error))
    return int(m.group(1)) if m else None


def _is_transient(error: Exception) -> bool:
    """True for errors worth retrying: rate limits, capacity blips, network drops."""
    if _error_code(error) in (429, 500, 502, 503, 504):
        return True
    text = str(error)
    return any(
        m in text
        for m in (
            "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand",
            # Local network failures — a DNS or socket blip says nothing about
            # the model, so retrying is right and switching models is not.
            "getaddrinfo", "Server disconnected", "Connection reset",
            "ConnectError", "ReadTimeout", "Temporary failure",
        )
    )


def _is_fatal(error: Exception) -> bool:
    """True for errors no retry or model swap can fix (bad key, bad request)."""
    if _error_code(error) in (401, 403):
        return True
    return any(
        m in str(error)
        for m in ("API key not valid", "PERMISSION_DENIED", "UNAUTHENTICATED")
    )


def _retry_after(error: Exception) -> Optional[float]:
    """Seconds Google asked us to wait, if the error says so."""
    text = str(error)
    for pattern in (r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", r"retry in (\d+(?:\.\d+)?)s"):
        m = re.search(pattern, text)
        if m:
            return min(float(m.group(1)), MAX_RETRY_WAIT)
    return None


class _RateLimiter:
    """Process-wide sliding-window throttle across every Mistral call."""

    def __init__(self):
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, rpm: int) -> None:
        if rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < rpm:
                    self._calls.append(now)
                    return
                wait = 60.0 - (now - self._calls[0]) + 0.05
            logger.info(f"Mistral throttle: {rpm}/min reached, waiting {wait:.1f}s")
            time.sleep(wait)


_limiter = _RateLimiter()


class ExtractedPost(BaseModel):
    """Structured fields pulled out of a LinkedIn hiring post."""
    is_hiring_post: bool = Field(description="True only if this post is advertising a job opening")
    emails: list[str] = Field(default_factory=list, description="Contact emails for applying")
    roles: list[str] = Field(default_factory=list, description="Job titles being hired for")
    experience: Optional[str] = Field(default=None, description="Required experience, e.g. '4-6 years'")
    locations: list[str] = Field(default_factory=list, description="Job locations, including Remote/Hybrid")
    company: Optional[str] = Field(default=None, description="Hiring company name")
    skills: list[str] = Field(default_factory=list, description="Key technical skills required")


class IndexedPost(ExtractedPost):
    index: int = Field(description="The POST number this refers to, as labelled in the input")


class ExtractedBatch(BaseModel):
    posts: list[IndexedPost]


class DraftedEmail(BaseModel):
    subject: str
    body_html: str


RULES = """Rules:
- is_hiring_post is false for general commentary, self-promotion, "I got a job" posts, \
or anything that is not an actual open role.
- emails: only real application contact addresses that appear in the text. Never invent one.
- roles: the job titles being hired for, normalised (e.g. "Senior Python Developer").
- experience: copy the stated requirement, e.g. "4-6 years", "3+ years". Null if absent.
- locations: cities/countries plus Remote/Hybrid/Onsite when stated.
- Return empty lists rather than guesses when the post does not say."""

BATCH_PROMPT = """You are parsing LinkedIn posts to decide which advertise job openings, \
and to pull out the details a job applicant needs.

{rules}

Return exactly one result object per post, each carrying the matching "index".

{posts}"""

DRAFT_PROMPT = """Write a short job application email responding to the LinkedIn hiring \
post below.

CRITICAL — the candidate's background is ONLY what the CANDIDATE section states.
- Never claim experience with a technology unless CANDIDATE explicitly lists it.
  If the post wants Java and CANDIDATE says Python, you must NOT write that the
  candidate has Java experience. Say they are keen to apply their existing
  skills to it, or simply do not mention it.
- Never invent employers, projects, degrees, years of experience, or metrics.
- If CANDIDATE is sparse, write a shorter and more general email. Do not pad it
  with plausible-sounding but unstated detail.

Style:
- Reference the specific role and company when the post names them.
- 120-160 words, warm but professional, no flattery or filler.
- Do not use placeholders like [Your Name] — the signature is handled separately.
- body_html must be simple HTML using only <p> tags.

CANDIDATE:
{candidate}

POST:
---
{content}
---"""


class AIExtractor:
    """Thin wrapper over Mistral. Safe to construct with no key configured."""

    def __init__(self):
        self._client = None
        self._init_error: Optional[str] = None

        if not settings.mistral_api_key:
            self._init_error = "MISTRAL_API_KEY not set"
            return
        try:
            from mistralai.client import Mistral
            self._client = Mistral(api_key=settings.mistral_api_key)
        except ImportError:
            self._init_error = "mistralai package not installed"
        except Exception as e:
            self._init_error = f"Mistral client init failed: {e}"

        if self._init_error:
            logger.info(f"AI extraction disabled: {self._init_error}")

    @property
    def model_chain(self) -> list[str]:
        """Configured model first, then fallbacks.

        Limits and availability differ per model, so a model that is throttled
        right now can be skipped in favour of one that is not.
        """
        chain = [settings.mistral_model]
        for m in settings.mistral_fallback_models.split(","):
            m = m.strip()
            if m and m not in chain:
                chain.append(m)
        return chain

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def status(self) -> str:
        return "ready" if self.available else (self._init_error or "unavailable")

    def _generate(self, prompt: str, schema, temperature: float):
        """One structured Mistral call, throttled, with retries and model fallback."""
        last_error = None
        for model in self.model_chain:
            for attempt in range(RETRY_ATTEMPTS):
                _limiter.acquire(settings.mistral_rpm)
                try:
                    response = self._client.chat.parse(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        response_format=schema,
                        temperature=temperature,
                    )
                    parsed = response.choices[0].message.parsed
                    if model != self.model_chain[0]:
                        logger.info(f"Mistral served by fallback model {model}")
                    return parsed
                except Exception as e:
                    last_error = e
                    if _is_fatal(e):
                        raise
                    if not _is_transient(e):
                        logger.warning(f"Mistral model {model} unusable: {e}")
                        break

                    wait = _retry_after(e)
                    # Rate-limited with a long wait: another model has its own
                    # allowance, so move on instead of sitting idle.
                    if attempt == RETRY_ATTEMPTS - 1 or (wait and wait > 10):
                        logger.info(
                            f"Mistral {model} rate-limited"
                            f"{f' (retry in {wait:.0f}s)' if wait else ''}; trying next model"
                        )
                        break
                    delay = wait or 2.0
                    logger.info(f"Mistral {model} busy, retrying in {delay:.0f}s")
                    time.sleep(delay)

        raise last_error

    async def extract_many(self, contents: list[str]) -> list[Optional[ExtractedPost]]:
        """Extract for several posts, batched to stay inside the free-tier quota."""
        results: list[Optional[ExtractedPost]] = [None] * len(contents)
        if not self.available or not contents:
            return results

        size = max(1, settings.mistral_batch_size)
        for start in range(0, len(contents), size):
            chunk = contents[start:start + size]
            try:
                batch = await asyncio.to_thread(self._extract_batch, chunk)
            except Exception as e:
                logger.warning(f"Mistral batch failed, those posts fall back to regex: {e}")
                continue
            if not batch:
                continue
            for item in batch.posts:
                # index is model-supplied; ignore anything out of range.
                if 0 <= item.index < len(chunk):
                    results[start + item.index] = item

        return results

    def _extract_batch(self, chunk: list[str]) -> Optional[ExtractedBatch]:
        blocks = "\n\n".join(
            f"POST {i}:\n---\n{c[:4000]}\n---" for i, c in enumerate(chunk)
        )
        return self._generate(
            BATCH_PROMPT.format(rules=RULES, posts=blocks), ExtractedBatch, 0.1
        )

    async def extract(self, content: str) -> Optional[ExtractedPost]:
        """Structured extraction for one post, or None if unavailable/failed."""
        if not self.available or not content:
            return None
        return (await self.extract_many([content]))[0]

    async def draft_email(self, content: str, candidate: str = "") -> Optional[DraftedEmail]:
        """Draft a tailored application email for a post."""
        if not self.available or not content:
            return None
        try:
            return await asyncio.to_thread(
                self._generate,
                DRAFT_PROMPT.format(
                    content=content[:8000],
                    candidate=candidate or "A software engineer applying for this role.",
                ),
                DraftedEmail,
                # Low temperature: creative phrasing is worth far less here than
                # not inventing skills the candidate never claimed.
                0.3,
            )
        except Exception as e:
            logger.warning(f"Mistral drafting failed: {e}")
            return None


# Shared instance — constructing the client per request is wasteful.
ai_extractor = AIExtractor()
