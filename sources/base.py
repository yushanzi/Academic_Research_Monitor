from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

import requests

from models import InterestProfile, Paper, ensure_paper

logger = logging.getLogger(__name__)

SCRAPE_TIMEOUT_SECONDS = 15
SCRAPE_MAX_ATTEMPTS = 3
SCRAPE_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
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


class PaperSource(ABC):
    """Abstract base class for all academic paper sources."""

    name: str = "unknown"

    @abstractmethod
    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        raise NotImplementedError

    def _cutoff_time(self, hours: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=hours)


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


def scrape_html_with_retries(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = SCRAPE_TIMEOUT_SECONDS,
    deadline_monotonic: float | None = None,
    context: str = "scrape",
):
    last_error = None

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

        try:
            response = requests.get(url, headers=headers, timeout=effective_timeout)
            if response.status_code in SCRAPE_RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(
                    f"retryable HTTP {response.status_code}",
                    response=response,
                )
            response.raise_for_status()
            return response
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in SCRAPE_RETRYABLE_STATUS_CODES:
                break
        except requests.RequestException as exc:
            last_error = exc
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
