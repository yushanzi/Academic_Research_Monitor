from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from models import InterestProfile, Paper, ensure_paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser-impersonation settings
# ---------------------------------------------------------------------------
IMPERSONATE = "chrome124"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": (
        '"Chromium";v="124", "Google Chrome";v="124", "Not?A_Brand";v="99"'
    ),
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# ---------------------------------------------------------------------------
# Scrape / retry configuration
# ---------------------------------------------------------------------------
SCRAPE_TIMEOUT_SECONDS = 15
SCRAPE_MAX_ATTEMPTS = 3
SCRAPE_RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}
SCRAPE_BACKOFF_BASE_SECONDS = 1.0
SCRAPE_BACKOFF_JITTER_SECONDS = 0.25

TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

# ---------------------------------------------------------------------------
# Cloudflare detection
# ---------------------------------------------------------------------------
CLOUDFLARE_MARKERS = (
    "cf-browser-verification",
    "cf-chl-bypass",
    "cf-challenge",
    "cf-captcha",
    "cf-please-wait",
    "cf-ray",
    "cf-turnstile",
    "checking your browser",
    "cloudflare",
    "enable javascript",
    "just a moment",
    "turnstile",
    "__cf_chl",
)


def is_cloudflare_block(response) -> bool:
    """Return True when *response* looks like a Cloudflare challenge / block page."""
    if response is None:
        return False
    status = getattr(response, "status_code", 0)
    if status in (403, 503):
        text = (getattr(response, "text", "") or "").lower()
        headers_lower = {
            k.lower(): v.lower()
            for k, v in (getattr(response, "headers", {}) or {}).items()
        }
        # Header check
        if headers_lower.get("server") == "cloudflare":
            return True
        if headers_lower.get("cf-ray"):
            return True
        # Body check
        if any(marker in text for marker in CLOUDFLARE_MARKERS):
            return True
    return False


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class PaperSource(ABC):
    """Abstract base class for all academic paper sources."""

    name: str = "unknown"

    @abstractmethod
    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        raise NotImplementedError

    def _cutoff_time(self, hours: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_paper(
    *,
    title: str,
    authors: list[str] | None,
    abstract: str,
    date: str,
    url: str,
    source: str,
    doi: str = "",
    pdf_url: str = "",
    landing_page_url: str | None = None,
) -> Paper:
    landing_page_url = landing_page_url or url or _doi_url(doi)
    entry_url = landing_page_url or _doi_url(doi)
    return Paper(
        title=title,
        authors=authors or [],
        abstract=abstract,
        date=date,
        url=url,
        source=source,
        doi=doi,
        pdf_url=pdf_url,
        landing_page_url=landing_page_url,
        entry_url=entry_url,
        download_url=pdf_url,
        full_text_available=False,
        full_text="",
        open_access=bool(pdf_url),
        effective_access_mode="open_access" if pdf_url else "abstract_only",
        evidence_level="abstract_only",
        matched_topics=[],
    )


def matches_topics(text: str, topics: list[str]) -> bool:
    return bool(find_matching_topics(text, topics))


def find_matching_topics(text: str, topics: list[str]) -> list[str]:
    if not text:
        return []
    text_lower = text.lower()
    text_normalized = re.sub(r"[^a-z0-9]+", " ", text_lower)
    text_tokens = set(text_normalized.split())
    matched_topics = []

    for topic in topics:
        topic_lower = topic.lower().strip()
        topic_normalized = re.sub(r"[^a-z0-9]+", " ", topic_lower).strip()

        if not topic_normalized:
            continue

        if topic_lower in text_lower or topic_normalized in text_normalized:
            matched_topics.append(topic)
            continue

        words = topic_normalized.split()
        significant_words = [
            word for word in words if len(word) >= 4 and word not in TOPIC_STOPWORDS
        ]
        if not significant_words:
            significant_words = words

        overlap = sum(1 for word in significant_words if word in text_tokens)
        required_overlap = min(len(significant_words), 2 if len(significant_words) <= 3 else 3)
        if overlap >= required_overlap:
            matched_topics.append(topic)

    return matched_topics


def matches_interest_profile(text: str, profile: InterestProfile) -> tuple[bool, list[str]]:
    if not text:
        return False, []

    text_lower = text.lower()
    excludes = [item.lower() for item in profile.exclude if item]
    if any(item in text_lower for item in excludes):
        return False, []

    if profile.must_have and not find_matching_topics(text, profile.must_have):
            return False, []

    candidates = list(dict.fromkeys(profile.core_topics + profile.synonyms + profile.must_have))
    matches = find_matching_topics(text, candidates)

    return bool(matches), matches


# ---------------------------------------------------------------------------
# HTTP fetching helpers
# ---------------------------------------------------------------------------


def _curl_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    impersonate: str = IMPERSONATE,
):
    """Thin wrapper around curl_cffi.requests.get with browser impersonation."""
    return requests.get(
        url,
        headers=headers or BROWSER_HEADERS,
        timeout=timeout,
        impersonate=impersonate,
        allow_redirects=True,
    )


def _playwright_fetch(url: str, timeout_ms: int = 15000) -> str | None:
    """Fetch page HTML via headless Chromium (Playwright).

    Returns the final page HTML, or *None* on failure.
    Handles Cloudflare JS challenges transparently."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright is not installed; cannot use browser fallback")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                extra_http_headers={
                    k: v
                    for k, v in BROWSER_HEADERS.items()
                    if k.lower() not in ("user-agent", "accept-encoding")
                },
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Give Cloudflare JS challenge a moment to complete
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return None


def fetch_with_browser_fallback(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    impersonate: str = IMPERSONATE,
    context: str = "fetch",
):
    """Fetch *url* via curl_cffi first; fall back to headless browser if blocked.

    Returns a ``requests``-like response object, or *None* on total failure.
    """
    response = _curl_get(url, headers=headers, timeout=timeout, impersonate=impersonate)
    if response is not None and not is_cloudflare_block(response):
        return response

    if response is not None and is_cloudflare_block(response):
        logger.info(
            "%s: Cloudflare block detected for %s (status %s); switching to browser",
            context,
            url,
            response.status_code,
        )

    # Browser fallback
    html = _playwright_fetch(url, timeout_ms=timeout * 1000)
    if html is None:
        logger.warning("%s: browser fallback also failed for %s", context, url)
        return None

    # Wrap the HTML in a response-like object so callers don't break
    class _BrowserResponse:
        def __init__(self, text: str, url: str, status_code: int = 200):
            self.text = text
            self.content = text.encode("utf-8")
            self.url = url
            self.status_code = status_code
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RequestsError(f"Browser fallback HTTP {self.status_code}")

    return _BrowserResponse(html, url)


def scrape_html_with_retries(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    deadline_monotonic: float | None = None,
    context: str = "scrape",
):
    """Fetch *url* with retry + browser-impersonation + Cloudflare fallback.

    First attempts via curl_cffi (TLS fingerprint mimicry).  On the last
    attempt, if the response looks like a Cloudflare block, Playwright is
    used as a headless-browser fallback."""
    last_error = None
    effective_headers = headers or BROWSER_HEADERS

    for attempt in range(1, SCRAPE_MAX_ATTEMPTS + 1):
        now = time.monotonic()
        if deadline_monotonic is not None and now >= deadline_monotonic:
            logger.warning("%s: skipping %s because scrape time budget was exhausted", context, url)
            return None

        effective_timeout = timeout
        if deadline_monotonic is not None:
            remaining = max(0.0, deadline_monotonic - now)
            if remaining <= 0:
                logger.warning("%s: skipping %s because scrape time budget was exhausted", context, url)
                return None
            effective_timeout = min(timeout, max(1.0, remaining))

        # --- Last attempt with Cloudflare detected → use browser fallback ---
        is_last = attempt == SCRAPE_MAX_ATTEMPTS
        if is_last:
            response = fetch_with_browser_fallback(
                url,
                headers=effective_headers,
                timeout=effective_timeout,
                impersonate=IMPERSONATE,
                context=context,
            )
            if response is not None:
                return response
            # fall through to logging
            last_error = RuntimeError("Cloudflare block persisted across all attempts")
            break

        # --- curl_cffi attempt ---
        try:
            response = _curl_get(
                url,
                headers=effective_headers,
                timeout=effective_timeout,
                impersonate=IMPERSONATE,
            )

            # Detect Cloudflare block early — retry with backoff
            if is_cloudflare_block(response):
                raise RequestsError(
                    f"Cloudflare block HTTP {response.status_code}",
                    response=response,
                )

            if response.status_code in SCRAPE_RETRYABLE_STATUS_CODES:
                raise RequestsError(
                    f"retryable HTTP {response.status_code}",
                    response=response,
                )
            response.raise_for_status()
            return response

        except RequestsError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            # Non-retryable status codes (e.g. non-Cloudflare 403): stop retrying.
            if status_code is not None and status_code not in SCRAPE_RETRYABLE_STATUS_CODES:
                if is_cloudflare_block(exc.response):
                    pass  # Cloudflare 403/503 → keep retrying
                else:
                    break
        except Exception as exc:
            last_error = exc
            break

        if attempt == SCRAPE_MAX_ATTEMPTS:
            break

        sleep_seconds = SCRAPE_BACKOFF_BASE_SECONDS * attempt + random.uniform(
            0,
            SCRAPE_BACKOFF_JITTER_SECONDS,
        )
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                break
            sleep_seconds = min(sleep_seconds, max(0.0, remaining))

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    logger.warning("%s: failed to fetch %s after retries: %s", context, url, last_error)
    return None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    seen: dict[str, Paper] = {}
    unique: list[Paper] = []
    for raw_paper in papers:
        paper = ensure_paper(raw_paper)
        doi = paper.doi
        if doi:
            key = doi.lower().strip()
        else:
            key = re.sub(r"\s+", " ", paper.title.lower().strip())

        if not key:
            continue

        if key not in seen:
            seen[key] = paper
            unique.append(paper)
            continue

        existing = seen[key]
        merged_topics = sorted(set(existing.matched_topics) | set(paper.matched_topics))
        if merged_topics:
            existing.matched_topics = merged_topics
        for field in (
            "abstract",
            "landing_page_url",
            "entry_url",
            "download_url",
            "pdf_url",
        ):
            if not getattr(existing, field) and getattr(paper, field):
                setattr(existing, field, getattr(paper, field))
    return unique


def _doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    return f"https://doi.org/{doi}" if doi else ""
