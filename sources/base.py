from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
SCRAPE_DEFAULT_FETCH_MODE = "browser_on_block"
SCRAPE_RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}
SCRAPE_BACKOFF_BASE_SECONDS = 1.0
SCRAPE_BACKOFF_JITTER_SECONDS = 0.25
SUPPORTED_FETCH_MODES = {"http_client", "browser_on_block", "browser_first"}

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


@dataclass
class FetchResult:
    ok: bool
    url: str
    status_code: int | None = None
    text: str = ""
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "http_client"
    blocked: bool = False
    rate_limited: bool = False
    error: str = ""
    challenge_detected: bool = False
    used_browser_fallback: bool = False

    def as_response(self):
        if not self.ok:
            return None
        return _FetchedResponse(self)


class PublisherSource(PaperSource):
    """Common fetch/runtime policy for publisher-backed RSS + article sources."""

    def __init__(
        self,
        *,
        fetch_mode: str | None = None,
        proxy_profile: str | None = None,
        browser_storage_state: str | None = None,
        min_request_interval_seconds: float | int | None = None,
        jitter_seconds: float | int | None = None,
        feed_only: bool = False,
        scraping: Any | None = None,
        network: Any | None = None,
    ):
        scraping_defaults = _config_to_dict(scraping)
        network_defaults = _config_to_dict(network)
        self.fetch_mode = _normalize_fetch_mode(
            fetch_mode or scraping_defaults.get("default_fetch_mode", SCRAPE_DEFAULT_FETCH_MODE)
        )
        self.proxy_profile = (proxy_profile or "").strip() or None
        self.browser_storage_state = (browser_storage_state or "").strip() or None
        self.min_request_interval_seconds = float(
            min_request_interval_seconds
            if min_request_interval_seconds is not None
            else scraping_defaults.get("default_min_request_interval_seconds", 0.0)
        )
        self.jitter_seconds = float(
            jitter_seconds if jitter_seconds is not None else scraping_defaults.get("default_jitter_seconds", 0.0)
        )
        self.feed_only = bool(feed_only)
        self.scraping_defaults = scraping_defaults
        self.network_defaults = network_defaults
        self._last_request_monotonic: float | None = None
        self._diagnostics = {
            phase: {
                "requests": 0,
                "successes": 0,
                "blocked": 0,
                "rate_limited": 0,
                "failures": 0,
                "fallbacks": 0,
                "http_status_counts": {},
                "last_status": "not_started",
            }
            for phase in ("discovery", "metadata", "document")
        }

    def get_diagnostics(self) -> dict[str, Any]:
        return _deep_copy_dict(self._diagnostics)

    def _resolve_proxy_url(self) -> str | None:
        proxies = self.network_defaults.get("proxies") or {}
        if not self.proxy_profile:
            return None
        proxy_url = str(proxies.get(self.proxy_profile, "")).strip()
        if proxy_url:
            return proxy_url
        logger.warning("%s: proxy profile '%s' is not defined", self.name, self.proxy_profile)
        return None

    def _throttle(self) -> None:
        min_interval = max(0.0, self.min_request_interval_seconds)
        if min_interval <= 0:
            return
        now = time.monotonic()
        if self._last_request_monotonic is not None:
            wait_seconds = min_interval - (now - self._last_request_monotonic)
            if self.jitter_seconds > 0:
                wait_seconds += random.uniform(0.0, self.jitter_seconds)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self._last_request_monotonic = time.monotonic()

    def _record_fetch_result(self, phase: str, result: FetchResult) -> None:
        phase_stats = self._diagnostics[phase]
        phase_stats["requests"] += 1
        if result.status_code is not None:
            counts = phase_stats["http_status_counts"]
            key = str(result.status_code)
            counts[key] = counts.get(key, 0) + 1
        if result.used_browser_fallback:
            phase_stats["fallbacks"] += 1
        if result.ok:
            phase_stats["successes"] += 1
            phase_stats["last_status"] = "ok"
            return
        if result.rate_limited:
            phase_stats["rate_limited"] += 1
            phase_stats["last_status"] = "rate_limited"
            return
        if result.blocked:
            phase_stats["blocked"] += 1
            phase_stats["last_status"] = "blocked"
            return
        phase_stats["failures"] += 1
        phase_stats["last_status"] = "failed"

    def _fetch_phase(
        self,
        url: str,
        *,
        phase: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        deadline_monotonic: float | None = None,
        fetch_mode: str | None = None,
        allow_browser: bool = True,
        expect_html: bool = True,
        context: str,
    ):
        self._throttle()
        result = fetch_url_with_retries(
            url,
            headers=headers,
            timeout=timeout or int(self.scraping_defaults.get("default_timeout_seconds", SCRAPE_TIMEOUT_SECONDS)),
            max_attempts=int(self.scraping_defaults.get("default_retry_attempts", SCRAPE_MAX_ATTEMPTS)),
            deadline_monotonic=deadline_monotonic,
            context=context,
            fetch_mode=_normalize_fetch_mode(fetch_mode or self.fetch_mode),
            proxy_url=self._resolve_proxy_url(),
            browser_storage_state=self.browser_storage_state,
            allow_browser=allow_browser,
            expect_html=expect_html,
        )
        self._record_fetch_result(phase, result)
        return result.as_response()


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


class _FetchedResponse:
    def __init__(self, result: FetchResult):
        self.text = result.text
        self.content = result.content
        self.url = result.url
        self.status_code = result.status_code or 200
        self.headers = result.headers
        self.fetch_result = result

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RequestsError(f"HTTP {self.status_code}")


def _config_to_dict(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def _deep_copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    cloned: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            cloned[key] = _deep_copy_dict(item)
        else:
            cloned[key] = item
    return cloned


def _normalize_fetch_mode(fetch_mode: str) -> str:
    normalized = str(fetch_mode or SCRAPE_DEFAULT_FETCH_MODE).strip() or SCRAPE_DEFAULT_FETCH_MODE
    if normalized not in SUPPORTED_FETCH_MODES:
        raise ValueError(f"Unsupported fetch_mode: {normalized}")
    return normalized


def _browser_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    merged = dict(BROWSER_HEADERS)
    if headers:
        merged.update(headers)
    return merged


def _looks_like_block_page(text: str) -> bool:
    body = (text or "").lower()
    if not body:
        return False
    return any(marker in body for marker in CLOUDFLARE_MARKERS)


def is_blocked_response(response) -> bool:
    if response is None:
        return False
    status = getattr(response, "status_code", 0) or 0
    if status in (403, 429, 503):
        return True
    return _looks_like_block_page(getattr(response, "text", "") or "")


def _curl_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    impersonate: str = IMPERSONATE,
    proxy_url: str | None = None,
):
    """Thin wrapper around curl_cffi.requests.get with browser impersonation."""
    return requests.get(
        url,
        headers=_browser_headers(headers),
        timeout=timeout,
        impersonate=impersonate,
        allow_redirects=True,
        proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None,
    )


def _playwright_fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_ms: int = 15000,
    proxy_url: str | None = None,
    storage_state: str | None = None,
) -> FetchResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright is not installed; cannot use browser fallback")
        return FetchResult(ok=False, url=url, error="playwright unavailable", method="browser")

    try:
        with sync_playwright() as pw:
            launch_kwargs = {"headless": True}
            if proxy_url:
                launch_kwargs["proxy"] = {"server": proxy_url}
            browser = pw.chromium.launch(**launch_kwargs)
            context_kwargs = {
                "user_agent": _browser_headers(headers)["User-Agent"],
                "extra_http_headers": {
                    k: v
                    for k, v in _browser_headers(headers).items()
                    if k.lower() not in ("user-agent", "accept-encoding")
                },
            }
            if storage_state and Path(storage_state).exists():
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(
                **context_kwargs,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)
            html = page.content()
            final_url = page.url
            browser.close()
            blocked = _looks_like_block_page(html)
            return FetchResult(
                ok=not blocked,
                url=final_url,
                status_code=200,
                text=html,
                content=html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
                method="browser",
                blocked=blocked,
                challenge_detected=blocked,
                error="challenge page persisted" if blocked else "",
                used_browser_fallback=True,
            )
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return FetchResult(ok=False, url=url, error=str(exc), method="browser", used_browser_fallback=True)


def fetch_with_browser_fallback(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    impersonate: str = IMPERSONATE,
    context: str = "fetch",
    proxy_url: str | None = None,
    browser_storage_state: str | None = None,
):
    response = _curl_get(
        url,
        headers=headers,
        timeout=timeout,
        impersonate=impersonate,
        proxy_url=proxy_url,
    )
    if response is not None and response.status_code < 400 and not _looks_like_block_page(getattr(response, "text", "")):
        return response

    if response is not None and is_blocked_response(response):
        logger.info("%s: block detected for %s (status %s); switching to browser", context, url, response.status_code)

    result = _playwright_fetch(
        url,
        headers=headers,
        timeout_ms=int(timeout * 1000),
        proxy_url=proxy_url,
        storage_state=browser_storage_state,
    )
    if not result.ok:
        logger.warning("%s: browser fallback failed for %s: %s", context, url, result.error or "blocked")
        return None
    return result.as_response()


def fetch_url_with_retries(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    max_attempts: int = SCRAPE_MAX_ATTEMPTS,
    deadline_monotonic: float | None = None,
    context: str = "fetch",
    fetch_mode: str = SCRAPE_DEFAULT_FETCH_MODE,
    proxy_url: str | None = None,
    browser_storage_state: str | None = None,
    allow_browser: bool = True,
    expect_html: bool = True,
    impersonate: str = IMPERSONATE,
):
    last_result = FetchResult(ok=False, url=url, error="request not attempted")

    def _merge_failure_results(primary: FetchResult, fallback: FetchResult) -> FetchResult:
        merged_status_code = primary.status_code if primary.status_code is not None else fallback.status_code
        merged_text = primary.text or fallback.text
        merged_content = primary.content or fallback.content
        merged_headers = dict(primary.headers or {})
        fallback_headers = fallback.headers if isinstance(fallback.headers, dict) else {}
        if not merged_headers and fallback_headers:
            merged_headers = dict(fallback_headers)
        merged_error = primary.error or fallback.error
        if primary.error and fallback.error and fallback.error not in primary.error:
            merged_error = f"{primary.error}; browser_fallback={fallback.error}"
        return FetchResult(
            ok=False,
            url=primary.url or fallback.url or url,
            status_code=merged_status_code,
            text=merged_text,
            content=merged_content,
            headers=merged_headers,
            method=fallback.method or primary.method,
            blocked=primary.blocked or fallback.blocked,
            rate_limited=primary.rate_limited or fallback.rate_limited,
            challenge_detected=primary.challenge_detected or fallback.challenge_detected,
            error=merged_error,
            used_browser_fallback=primary.used_browser_fallback or fallback.used_browser_fallback,
        )

    mode = _normalize_fetch_mode(fetch_mode)
    effective_headers = _browser_headers(headers)
    for attempt in range(1, max_attempts + 1):
        now = time.monotonic()
        if deadline_monotonic is not None and now >= deadline_monotonic:
            return FetchResult(ok=False, url=url, error="deadline exhausted")
        effective_timeout = timeout
        if deadline_monotonic is not None:
            remaining = max(0.0, deadline_monotonic - now)
            if remaining <= 0:
                return FetchResult(ok=False, url=url, error="deadline exhausted")
            effective_timeout = min(timeout, max(1.0, int(remaining)))

        if allow_browser and expect_html and mode == "browser_first":
            browser_result = _playwright_fetch(
                url,
                headers=effective_headers,
                timeout_ms=int(effective_timeout * 1000),
                proxy_url=proxy_url,
                storage_state=browser_storage_state,
            )
            if browser_result.ok:
                return browser_result
            last_result = browser_result

        try:
            response = _curl_get(
                url,
                headers=effective_headers,
                timeout=effective_timeout,
                impersonate=impersonate,
                proxy_url=proxy_url,
            )
        except Exception as exc:
            last_result = FetchResult(ok=False, url=url, error=str(exc), method="http_client")
            response = None

        if response is not None:
            status_code = getattr(response, "status_code", None)
            text = getattr(response, "text", "") or ""
            blocked = is_blocked_response(response) if expect_html else status_code in (403, 429, 503)
            rate_limited = status_code == 429
            ok = status_code is not None and status_code < 400 and not blocked
            if ok:
                return FetchResult(
                    ok=True,
                    url=str(getattr(response, "url", "") or url),
                    status_code=status_code,
                    text=text,
                    content=getattr(response, "content", b"") or text.encode("utf-8"),
                    headers=dict(getattr(response, "headers", {}) or {}),
                    method="http_client",
                )

            last_result = FetchResult(
                ok=False,
                url=str(getattr(response, "url", "") or url),
                status_code=status_code,
                text=text,
                content=getattr(response, "content", b"") or text.encode("utf-8"),
                headers=dict(getattr(response, "headers", {}) or {}),
                method="http_client",
                blocked=blocked,
                rate_limited=rate_limited,
                challenge_detected=_looks_like_block_page(text),
                error=f"HTTP {status_code}" if status_code is not None else "request failed",
            )
            should_browser_fallback = allow_browser and expect_html and mode == "browser_on_block" and (
                blocked or rate_limited
            )
            if should_browser_fallback:
                http_failure = last_result
                browser_result = _playwright_fetch(
                    url,
                    headers=effective_headers,
                    timeout_ms=int(effective_timeout * 1000),
                    proxy_url=proxy_url,
                    storage_state=browser_storage_state,
                )
                if browser_result.ok:
                    return browser_result
                last_result = _merge_failure_results(http_failure, browser_result)

            if status_code is not None and status_code < 500 and status_code not in (403, 429, 503):
                break

        if attempt == max_attempts:
            break
        sleep_seconds = SCRAPE_BACKOFF_BASE_SECONDS * attempt + random.uniform(0, SCRAPE_BACKOFF_JITTER_SECONDS)
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                break
            sleep_seconds = min(sleep_seconds, max(0.0, remaining))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    logger.warning("%s: failed to fetch %s after retries: %s", context, url, last_result.error)
    return last_result


def scrape_html_with_retries(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    max_attempts: int = SCRAPE_MAX_ATTEMPTS,
    deadline_monotonic: float | None = None,
    context: str = "scrape",
    fetch_mode: str = SCRAPE_DEFAULT_FETCH_MODE,
    proxy_url: str | None = None,
    browser_storage_state: str | None = None,
):
    result = fetch_url_with_retries(
        url,
        headers=headers,
        timeout=timeout,
        max_attempts=max_attempts,
        deadline_monotonic=deadline_monotonic,
        context=context,
        fetch_mode=fetch_mode,
        proxy_url=proxy_url,
        browser_storage_state=browser_storage_state,
        allow_browser=True,
        expect_html=True,
    )
    return result.as_response()


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
