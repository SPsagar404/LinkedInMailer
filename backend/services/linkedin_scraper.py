"""
LinkedIn Post Scraper using Playwright.
Scrapes LinkedIn search results for posts containing hiring info.
"""
import asyncio
import json
import os
import random
import re
import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from config import settings
from services.ai_extractor import ai_extractor
from services.query_expander import build_queries
from services.data_extractor import DataExtractor

logger = logging.getLogger("LinkedInScraper")
logging.basicConfig(level=logging.INFO)


class LinkedInScraper:
    """Scrapes LinkedIn posts using Playwright browser automation."""

    SEARCH_URL = "https://www.linkedin.com/search/results/content/"
    LOGIN_URL = "https://www.linkedin.com/login"

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.extractor = DataExtractor()

    async def _random_delay(self, min_sec: float = None, max_sec: float = None):
        """Human-like random delay between actions."""
        min_s = min_sec or settings.scrape_delay_min
        max_s = max_sec or settings.scrape_delay_max
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)

    async def _init_browser(self):
        """Launch browser with stealth settings."""
        # Held on the instance so _cleanup() can stop the driver — otherwise every
        # scrape job leaks the Playwright node subprocess for the life of the server.
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,  # LinkedIn detects headless more easily
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        # Try to load saved cookies for session persistence
        if os.path.exists(settings.cookies_path):
            self.context = await self.browser.new_context(
                storage_state=settings.cookies_path,
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
        else:
            self.context = await self.browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        self.page = await self.context.new_page()

        # NOTE: stealth_async() is deliberately not called here. playwright-stealth
        # 1.0.6 is incompatible with playwright 1.47 — its injected scripts throw
        # "utils is not defined" / "log is not defined", which leaves LinkedIn
        # rendering a blank page. Running without it renders correctly.
        # The launch args in _init_browser already hide the automation flag.

    async def _login(self):
        """Login to LinkedIn using credentials."""
        logger.info("Logging into LinkedIn...")
        # "networkidle" never settles on LinkedIn — it keeps background requests
        # running, so goto() times out. Wait for the login form itself instead.
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        logger.info(f"Login page loaded: {self.page.url}")

        # LinkedIn's current login page generates random per-load element ids
        # (React useId, e.g. "«Rsvvd3ksopa55j6»"), has no name attributes and no
        # <form> element at all, so #username / session_key no longer exist.
        # Input *type* plus :visible is the stable handle. The page also renders
        # duplicate hidden responsive copies of each field, hence :visible.
        email_field = self.page.locator('input[type="email"]:visible').first
        password_field = self.page.locator('input[type="password"]:visible').first

        try:
            await email_field.wait_for(state="visible", timeout=30000)
        except Exception:
            # Not a form we recognise — capture the page so this is diagnosable
            # instead of just a selector timeout.
            shot = os.path.join(os.path.dirname(settings.cookies_path), "login_debug.png")
            try:
                await self.page.screenshot(path=shot, full_page=True)
            except Exception:
                shot = "(screenshot failed)"
            title = await self.page.title()
            raise RuntimeError(
                f"No LinkedIn sign-in form found. url={self.page.url!r} "
                f"title={title!r}. Screenshot saved to {shot}. "
                "If this is a captcha/authwall, log in manually in the browser "
                "window once so cookies get saved."
            )

        await self._random_delay(1, 2)

        # Type email
        await email_field.fill(settings.linkedin_email)
        await self._random_delay(0.5, 1.5)

        # Type password
        await password_field.fill(settings.linkedin_password)
        await self._random_delay(0.5, 1)

        # Click sign in. The button is type="button" (not submit) and sits outside
        # any form, so it has to be matched by its accessible name. exact=True
        # avoids the "Sign in with Microsoft" / "Sign in with Apple" buttons.
        await self.page.get_by_role("button", name="Sign in", exact=True).first.click()

        # Wait for navigation to complete
        try:
            await self.page.wait_for_url("**/feed/**", timeout=30000)
            logger.info("Login successful!")
        except Exception:
            # Check for security verification
            current_url = self.page.url
            if "checkpoint" in current_url or "challenge" in current_url:
                logger.warning(
                    "LinkedIn security challenge detected! "
                    "Please complete the verification manually in the browser window. "
                    "Waiting 60 seconds..."
                )
                await asyncio.sleep(60)
            else:
                logger.warning(f"Login may have failed. Current URL: {current_url}")

        # Save cookies for future sessions
        await self._save_cookies()

    async def _save_cookies(self):
        """Save browser cookies to avoid re-login."""
        try:
            await self.context.storage_state(path=settings.cookies_path)
            logger.info("Cookies saved successfully.")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    async def _is_logged_in(self) -> bool:
        """Check if we're already logged in."""
        try:
            await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
            await self._random_delay(2, 3)
            current_url = self.page.url
            return "feed" in current_url and "login" not in current_url
        except Exception:
            return False

    # LinkedIn's search page sets overflow-y:hidden on <body> and scrolls an
    # inner <main> instead, so window.scrollTo() moves nothing and only the
    # first ~12 results ever load. This finds the element that actually scrolls
    # and drives that, which lets the infinite scroll fire (~6 more per pass).
    _SCROLL_JS = r"""
    () => {
        let el = null;
        document.querySelectorAll('div,main,section').forEach(e => {
            const st = getComputedStyle(e);
            if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                e.scrollHeight > e.clientHeight + 50) {
                if (!el || e.scrollHeight > el.scrollHeight) el = e;
            }
        });
        const target = el || document.scrollingElement || document.body;
        target.scrollTop = target.scrollHeight;
        // Harmless when the body is not the scroller; needed when it is.
        window.scrollTo(0, document.body.scrollHeight);
        return target.scrollHeight;
    }
    """

    async def _scroll_and_load(self, num_scrolls: int = None) -> int:
        """Scroll the results list to pull in more pages of posts.

        Returns the number of scroll passes actually performed. Stops early once
        the list stops growing — LinkedIn caps each query well before an
        unlimited feed, and scrolling a static page just wastes time.
        """
        passes = num_scrolls or settings.scroll_pages_per_query
        last_height, stalls = 0, 0

        for i in range(passes):
            height = await self.page.evaluate(self._SCROLL_JS)
            await self._random_delay(1.5, 3)

            if height == last_height:
                stalls += 1
                if stalls >= 3:
                    logger.info(
                        f"Scroll {i + 1}/{passes}: list stopped growing, moving on"
                    )
                    return i + 1
            else:
                stalls = 0
            last_height = height
            logger.info(f"Scroll {i + 1}/{passes} (list height {height})")

        return passes

    # LinkedIn's search results are server-driven (SDUI) and every class name is a
    # build hash (e.g. "_85566b33 _867f7357"), so it changes on each deploy — class
    # and id selectors cannot work, and there are no longer any urn:li:activity
    # attributes to anchor on. Instead we find the results list by shape (the
    # deepest element with 3+ text-heavy children) and read each card's text/links.
    _CARDS_JS = r"""
    () => {
        // Pick the container with the MOST post-like children, not the deepest.
        // Depth alone is unstable: once enough posts load, a nested block inside
        // a single post can become the deepest qualifying element, and the
        // extraction silently collapses to a handful of cards.
        let best = null, bestCount = 0, bestDepth = -1;
        document.querySelectorAll('div,ul,section,main').forEach(p => {
            const kids = Array.from(p.children);
            if (kids.length < 3) return;
            const rich = kids.filter(k => (k.innerText || '').trim().length > 150);
            if (rich.length < 3) return;
            let d = 0, e = p;
            while (e.parentElement) { d++; e = e.parentElement; }
            if (rich.length > bestCount ||
                (rich.length === bestCount && d > bestDepth)) {
                bestCount = rich.length; bestDepth = d; best = p;
            }
        });
        if (!best) return [];

        return Array.from(best.children)
            .filter(k => (k.innerText || '').trim().length > 150)
            .map(card => {
                const profile = card.querySelector('a[href*="/in/"]');
                const post = card.querySelector('a[href*="/feed/update/"], a[href*="/posts/"]');
                return {
                    text: (card.innerText || '').trim(),
                    profile_url: profile ? profile.href.split('?')[0] : null,
                    post_url: post ? post.href.split('?')[0] : null,
                };
            });
    }
    """

    # Header/footer chrome that surrounds the real post body inside a card.
    _CARD_NOISE = {
        "feed post", "promoted", "follow", "following", "join", "connect",
        "like", "comment", "repost", "send", "see more", "…more", "...more",
        "more", "see translation",
    }
    # A timestamp is its OWN line: "12h •", "1d", "3w • Edited". Matching the
    # whole line matters — a prefix match would also hit body text like
    # "5 years experience". Cards don't agree on where this line sits, so it is
    # searched for rather than assumed to be at a fixed index.
    _TIMESTAMP_RE = re.compile(
        r"^(\d+)\s*(s|m|h|d|w|mo|y)\s*(?:•.*)?$", re.IGNORECASE
    )
    # "• 3rd+", "• 2nd" — the connection degree always follows the author name.
    _DEGREE_RE = re.compile(r"^\s*•?\s*(?:1st|2nd|3rd)\+?\s*$", re.IGNORECASE)

    # Relative age → seconds. LinkedIn only shows "5h"/"4d", never a real date,
    # so posted_at is an approximation good to the displayed precision.
    _AGE_UNITS = {
        "s": 1, "m": 60, "h": 3600, "d": 86400,
        "w": 604800, "mo": 2592000, "y": 31536000,
    }

    @classmethod
    def _posted_at_from_age(cls, age: Optional[str]) -> Optional[datetime]:
        """Approximate absolute post time from a relative age like '5h'."""
        if not age:
            return None
        m = cls._TIMESTAMP_RE.match(age)
        if not m:
            return None
        seconds = int(m.group(1)) * cls._AGE_UNITS.get(m.group(2), 0)
        return datetime.utcnow() - timedelta(seconds=seconds) if seconds else datetime.utcnow()

    def _parse_card_text(self, text: str) -> dict:
        """Split a card's visible text into author / headline / post body."""
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return {"author_name": None, "author_headline": None, "content": "",
                    "posted_ago": None}

        # Drop a leading "Feed post" / "Promoted" label if present.
        idx = 0
        while idx < len(lines) and lines[idx].lower() in {"feed post", "promoted"}:
            idx += 1

        # Card layouts vary: some open with the author, others with the post body
        # and name the author further down. The connection degree ("• 3rd+")
        # reliably follows the author name, so anchor on that when present.
        deg_i = next(
            (i for i, ln in enumerate(lines) if self._DEGREE_RE.match(ln)), None
        )
        if deg_i is not None and deg_i > 0:
            author = lines[deg_i - 1]
        else:
            # No degree marker. Only trust the first line as a name if it looks
            # like one — otherwise it is the post body, and a wrong author is
            # worse than none.
            first = lines[idx] if idx < len(lines) else None
            author = first if (first and len(first) <= 60) else None
        # The name line sometimes carries the degree inline: "Sai Rajeshwar • 3rd+"
        if author and "•" in author:
            author = author.split("•")[0].strip() or None

        # Find the timestamp line anywhere in the card, not at a fixed offset.
        ts_i = next(
            (i for i, ln in enumerate(lines) if self._TIMESTAMP_RE.match(ln)),
            None,
        )
        # The headline sits between the author and the timestamp.
        headline = None
        headline_i = None
        if deg_i is not None and ts_i is not None and deg_i < ts_i:
            for i in range(deg_i + 1, ts_i):
                ln = lines[i]
                if ln.startswith("•") or ln.lower() in self._CARD_NOISE:
                    continue
                # Strip a trailing connection degree ("Sai Rajeshwar • 3rd+"),
                # but leave "•" alone when it is just a separator in the headline.
                headline = re.sub(r"\s*•\s*(?:1st|2nd|3rd)\+?\s*$", "", ln).strip() or None
                headline_i = i
                break

        # Body = everything that is not header chrome. Slicing after the
        # timestamp would lose the post text on cards that lead with content and
        # name the author further down.
        header_idx = {i for i in range(idx)}          # "Feed post" / "Promoted"
        for i in (deg_i, ts_i, headline_i):
            if i is not None:
                header_idx.add(i)
        if deg_i is not None and deg_i > 0:
            header_idx.add(deg_i - 1)                  # the author name line

        body: list[str] = []
        for i, ln in enumerate(lines):
            if i in header_idx:
                continue
            if ln.lower() in self._CARD_NOISE or self._DEGREE_RE.match(ln):
                continue
            body.append(ln)

        # Trim trailing engagement chrome ("Like", "Comment", counts, …).
        while body and (
            body[-1].lower() in self._CARD_NOISE
            or re.fullmatch(r"[\d,.]+\s*(?:likes?|comments?|reposts?)?", body[-1], re.I)
        ):
            body.pop()

        return {
            "author_name": author,
            "author_headline": headline[:500] if headline else None,
            "content": "\n".join(body).strip(),
            # The card's relative age ("5h", "4d") — the only date LinkedIn shows.
            "posted_ago": lines[ts_i] if ts_i is not None else None,
        }

    async def _extract_posts(self, max_posts: int = 10) -> list[dict]:
        """Extract post data from the current search results page."""
        try:
            cards = await self.page.evaluate(self._CARDS_JS)
        except Exception as e:
            logger.warning(f"Card extraction failed: {e}")
            cards = []

        if not cards:
            shot = os.path.join(os.path.dirname(settings.cookies_path), "search_debug.png")
            try:
                await self.page.screenshot(path=shot, full_page=False)
            except Exception:
                shot = "(screenshot failed)"
            logger.warning(
                f"No post cards found on {self.page.url}. Screenshot: {shot}"
            )
            return []

        logger.info(f"Found {len(cards)} post cards")

        posts = []
        for card in cards:
            if len(posts) >= max_posts:
                break
            try:
                parsed = self._parse_card_text(card.get("text", ""))
                # content is NOT NULL in the DB, and a card with no body is chrome.
                if len(parsed["content"]) < 20:
                    continue
                posts.append({
                    "author_name": parsed["author_name"],
                    "author_headline": parsed["author_headline"],
                    "author_profile_url": card.get("profile_url"),
                    "content": parsed["content"],
                    "post_url": card.get("post_url"),
                    "posted_ago": parsed["posted_ago"],
                    "posted_at": self._posted_at_from_age(parsed["posted_ago"]),
                })
                logger.info(f"Extracted post {len(posts)}/{max_posts}")
            except Exception as e:
                logger.warning(f"Failed to parse card: {e}")
                continue

        return posts

    # LinkedIn's own content-search filters. Verified against the live site:
    # sortBy="date_posted" returns posts minutes old, datePosted="past-24h"
    # restricts to the last day. There is no arbitrary from/to date filter —
    # exact ranges are applied afterwards using each post's displayed age.
    DATE_WINDOWS = {"past-24h", "past-week", "past-month"}

    def _build_search_url(
        self,
        search_query: str,
        date_posted: Optional[str] = None,
        sort_by_latest: bool = True,
    ) -> str:
        params = {"keywords": search_query, "origin": "GLOBAL_SEARCH_HEADER"}
        if date_posted in self.DATE_WINDOWS:
            # LinkedIn expects the value wrapped in literal double quotes.
            params["datePosted"] = f'"{date_posted}"'
        if sort_by_latest:
            params["sortBy"] = '"date_posted"'
        return self.SEARCH_URL + "?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote
        )

    async def _enrich(self, raw_posts: list[dict]) -> list[dict]:
        """Attach extracted emails/roles/experience/location to raw posts.

        Mistral does this far better than the regex/spaCy extractor when a key is
        configured; ai_results is all-None otherwise, and any individual failure
        falls back to regex for that post alone.
        """
        contents = [p.get("content", "") for p in raw_posts]
        ai_results = await ai_extractor.extract_many(contents)
        if ai_extractor.available:
            ok = sum(1 for r in ai_results if r is not None)
            logger.info(f"AI extraction: {ok}/{len(contents)} posts enriched by Mistral")

        enriched = []
        for post, ai in zip(raw_posts, ai_results):
            extracted = self.extractor.extract_all(post.get("content", ""))
            # Prefer AI values, but never let it erase something regex found —
            # notably emails, which regex is already reliable at.
            emails = (ai.emails if ai and ai.emails else extracted["emails"])
            roles = (ai.roles if ai and ai.roles else extracted["roles"])
            experience = (ai.experience if ai and ai.experience else extracted["experience"])
            locations = (ai.locations if ai and ai.locations else extracted["locations"])
            post.update({
                "extracted_emails": ",".join(emails) if emails else None,
                "extracted_roles": ",".join(roles) if roles else None,
                "extracted_experience": experience,
                "extracted_location": ",".join(locations) if locations else None,
                # Only the AI extractor identifies the hiring company; regex has
                # no equivalent, so this is None on the fallback path.
                "extracted_company": (ai.company if ai else None),
            })
            enriched.append(post)
        return enriched

    async def _collect_for_query(self, query, date_posted, sort_by_latest, seen_keys):
        """Load one query and return its not-yet-seen raw posts."""
        url = self._build_search_url(query, date_posted, sort_by_latest)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await self._random_delay(3, 5)
        # Scroll through several pages of infinite scroll; each pass adds ~6 posts.
        await self._scroll_and_load()

        fresh = []
        for post in await self._extract_posts(max_posts=1000):
            key = re.sub(r"\s+", " ", (post.get("content") or "")).strip().lower()[:300]
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            post["source_query"] = query
            fresh.append(post)
        return fresh

    async def scrape_many(
        self,
        title: str,
        target_posts: int = 200,
        date_posted: Optional[str] = None,
        sort_by_latest: bool = True,
        progress=None,
        min_new_emails: int = 0,
        known_emails: Optional[set] = None,
        extra_queries: Optional[list] = None,
    ) -> list[dict]:
        """Run expanded queries until `target_posts` unique posts are collected.

        LinkedIn caps a single search at ~12 results, so reaching a few hundred
        means many searches merged together. Duplicates are dropped as we go:
        the same post surfaces under several phrasings.

        `min_new_emails` is a floor on *previously unseen* addresses: the run
        keeps searching past the post target until that many new emails are
        found, because a scrape that only re-finds known contacts is worthless.
        `known_emails` is the set already in the database.
        """
        known = {e.strip().lower() for e in (known_emails or set()) if e}
        new_emails: set[str] = set()
        # Chasing an email floor may need more phrasings than the post target implies.
        queries = build_queries(
            title, max(target_posts, min_new_emails * 25 if min_new_emails else 0)
        )
        # Caller-supplied terms go first — they are explicit intent, so they
        # should be searched before anything the expander guessed at.
        for extra in reversed([q.strip() for q in (extra_queries or []) if q and q.strip()]):
            if extra in queries:
                queries.remove(extra)
            queries.insert(0, extra)
        logger.info(
            f"Multi-query scrape: target={target_posts}, {len(queries)} query variants"
        )

        await self._init_browser()
        if not await self._is_logged_in():
            await self._login()
        await self._random_delay(2, 4)

        collected: list[dict] = []
        seen_keys: set[str] = set()
        empty_streak = 0

        try:
          for i, query in enumerate(queries, 1):
            posts_done = len(collected) >= target_posts
            emails_done = len(new_emails) >= min_new_emails
            if posts_done and emails_done:
                logger.info(
                    f"Targets met after {i - 1} queries: {len(collected)} posts, "
                    f"{len(new_emails)} new emails"
                )
                break
            try:
                fresh = await self._collect_for_query(
                    query, date_posted, sort_by_latest, seen_keys
                )
            except Exception as e:
                logger.warning(f"Query {query!r} failed: {e}")
                continue

            # Enrich now rather than at the end: the email floor can only be
            # evaluated once addresses have actually been extracted.
            if fresh:
                fresh = await self._enrich(fresh)
                for p in fresh:
                    for addr in (p.get("extracted_emails") or "").split(","):
                        addr = addr.strip().lower()
                        if addr and "@" in addr and addr not in known:
                            new_emails.add(addr)

            collected.extend(fresh)
            logger.info(
                f"[{i}/{len(queries)}] {query!r}: +{len(fresh)} posts "
                f"(total {len(collected)}/{target_posts}, "
                f"new emails {len(new_emails)}/{min_new_emails or '-'})"
            )
            if progress:
                try:
                    await progress(len(collected), i, len(queries), len(new_emails))
                except Exception:
                    pass

            # Several consecutive queries adding nothing means the phrasings have
            # converged on the same results; more searching just burns time and
            # raises the odds of LinkedIn throttling us.
            empty_streak = empty_streak + 1 if not fresh else 0
            if empty_streak >= 6 and len(new_emails) >= min_new_emails:
                logger.info("6 queries in a row returned nothing new — stopping early")
                break
            if empty_streak >= 12:
                # Still short of the email floor, but LinkedIn has stopped
                # returning anything new. Pushing further just risks throttling.
                logger.warning(
                    f"Exhausted queries with {len(new_emails)}/{min_new_emails} "
                    "new emails — LinkedIn returned no further unique results"
                )
                break

            await self._random_delay(2, 4)
        finally:
            await self._save_cookies()
            await self._cleanup()

        # Never truncate away posts that carry a new email — they are the point.
        if target_posts and len(collected) > target_posts:
            with_email = [p for p in collected if p.get("extracted_emails")]
            without = [p for p in collected if not p.get("extracted_emails")]
            collected = (with_email + without)[:max(target_posts, len(with_email))]
        logger.info(
            f"Multi-query scrape done: {len(collected)} unique posts, "
            f"{len(new_emails)} new email addresses"
        )
        return collected

    async def scrape(
        self,
        search_query: str,
        max_posts: int = 10,
        date_posted: Optional[str] = None,
        sort_by_latest: bool = True,
    ) -> list[dict]:
        """
        Main scraping method.
        1. Init browser
        2. Login (if needed)
        3. Search for posts (optionally newest-first / within a date window)
        4. Scroll & extract posts
        5. Run data extraction on each post
        6. Return structured data
        """
        try:
            await self._init_browser()

            # Check if logged in, login if not
            is_logged_in = await self._is_logged_in()
            if not is_logged_in:
                await self._login()

            await self._random_delay(2, 4)

            # Navigate to search results (content/posts filter)
            search_url = self._build_search_url(search_query, date_posted, sort_by_latest)
            logger.info(f"Navigating to: {search_url}")
            await self.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._random_delay(3, 5)

            # Scroll to load more posts
            num_scrolls = max(3, max_posts // 3)
            await self._scroll_and_load(num_scrolls)

            # Extract raw posts
            raw_posts = await self._extract_posts(max_posts)
            logger.info(f"Extracted {len(raw_posts)} raw posts")

            # Enrich each post. Mistral does this far better than the regex/spaCy
            # extractor when a key is configured; ai_results is all-None otherwise,
            # and any individual failure falls back to regex for that post alone.
            contents = [p.get("content", "") for p in raw_posts]
            ai_results = await ai_extractor.extract_many(contents)
            if ai_extractor.available:
                ok = sum(1 for r in ai_results if r is not None)
                logger.info(f"AI extraction: {ok}/{len(contents)} posts enriched by Mistral")

            enriched_posts = []
            for post, ai in zip(raw_posts, ai_results):
                extracted = self.extractor.extract_all(post.get("content", ""))

                # Prefer AI values, but never let it erase something regex found —
                # notably emails, which regex is already reliable at.
                emails = (ai.emails if ai and ai.emails else extracted["emails"])
                roles = (ai.roles if ai and ai.roles else extracted["roles"])
                experience = (ai.experience if ai and ai.experience else extracted["experience"])
                locations = (ai.locations if ai and ai.locations else extracted["locations"])

                post.update({
                    "extracted_emails": ",".join(emails) if emails else None,
                    "extracted_roles": ",".join(roles) if roles else None,
                    "extracted_experience": experience,
                    "extracted_location": ",".join(locations) if locations else None,
                })
                enriched_posts.append(post)

            # Save cookies for next time
            await self._save_cookies()

            return enriched_posts

        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self):
        """Close browser resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
