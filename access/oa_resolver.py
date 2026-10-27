from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from sources.base import BROWSER_HEADERS, fetch_url_with_retries

logger = logging.getLogger(__name__)

OPENALEX_WORKS_API = "https://api.openalex.org/works/"
JSON_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "application/json",
}
PUBLISHER_LIKE_HOSTS = {
    "science": {"doi.org", "science.org", "www.science.org", "sciencemag.org", "www.sciencemag.org"},
    "acs": {"doi.org", "pubs.acs.org"},
    "nature": {"doi.org", "nature.com", "www.nature.com"},
}
VERSION_PRIORITY = {
    "publishedVersion": 3,
    "acceptedVersion": 2,
    "submittedVersion": 1,
}
EXTERNAL_FIRST_SOURCES = {"science", "acs"}


@dataclass(frozen=True)
class OALocationCandidate:
    landing_page_url: str = ""
    pdf_url: str = ""
    source_display_name: str = ""
    source_type: str = ""
    version: str = ""
    is_best_oa: bool = False


def resolve_open_access_locations(
    doi: str,
    *,
    source_key: str,
    proxy_url: str | None = None,
) -> list[OALocationCandidate]:
    payload = _fetch_openalex_work_payload(doi, proxy_url=proxy_url)
    if not payload:
        return []

    raw_candidates: list[tuple[dict, bool]] = []
    best_oa_location = payload.get("best_oa_location")
    if isinstance(best_oa_location, dict):
        raw_candidates.append((best_oa_location, True))
    for raw_location in payload.get("locations") or []:
        if isinstance(raw_location, dict):
            raw_candidates.append((raw_location, False))

    deduped: dict[tuple[str, str], OALocationCandidate] = {}
    for raw_location, is_best_oa in raw_candidates:
        candidate = _build_candidate(raw_location, is_best_oa=is_best_oa)
        if candidate is None:
            continue
        key = (candidate.landing_page_url, candidate.pdf_url)
        existing = deduped.get(key)
        if existing is None or _candidate_priority(candidate, source_key) > _candidate_priority(existing, source_key):
            deduped[key] = candidate

    return sorted(
        deduped.values(),
        key=lambda candidate: _candidate_priority(candidate, source_key),
        reverse=True,
    )


def resolve_openalex_abstract(
    doi: str,
    *,
    proxy_url: str | None = None,
) -> str:
    payload = _fetch_openalex_work_payload(doi, proxy_url=proxy_url)
    if not payload:
        return ""

    abstract_inverted_index = payload.get("abstract_inverted_index") or {}
    return _reconstruct_abstract(abstract_inverted_index)


def looks_like_publisher_location(candidate: OALocationCandidate, source_key: str) -> bool:
    source_type = (candidate.source_type or "").strip().lower()
    if source_type == "repository":
        return False

    hosts = PUBLISHER_LIKE_HOSTS.get(source_key, set())
    if not hosts:
        return False

    for url in (candidate.landing_page_url, candidate.pdf_url):
        host = _hostname(url)
        if host and host in hosts:
            return True
    return False


def _build_candidate(raw_location: dict, *, is_best_oa: bool) -> OALocationCandidate | None:
    if not raw_location.get("is_oa"):
        return None

    landing_page_url = str(raw_location.get("landing_page_url") or "").strip()
    pdf_url = str(raw_location.get("pdf_url") or "").strip()
    if not landing_page_url and not pdf_url:
        return None

    source = raw_location.get("source") or {}
    return OALocationCandidate(
        landing_page_url=landing_page_url,
        pdf_url=pdf_url,
        source_display_name=str(source.get("display_name") or "").strip(),
        source_type=str(source.get("type") or "").strip(),
        version=str(raw_location.get("version") or "").strip(),
        is_best_oa=is_best_oa,
    )


def _fetch_openalex_work_payload(
    doi: str,
    *,
    proxy_url: str | None = None,
) -> dict:
    doi_url = _doi_url(doi)
    if not doi_url:
        return {}

    endpoint = OPENALEX_WORKS_API + quote(doi_url, safe="")
    result = fetch_url_with_retries(
        endpoint,
        headers=JSON_HEADERS,
        timeout=20,
        max_attempts=2,
        context="OpenAlex work fetch",
        fetch_mode="http_client",
        proxy_url=proxy_url,
        allow_browser=False,
        expect_html=False,
    )
    if not result.ok:
        logger.debug("OpenAlex work fetch failed for DOI %s: %s", doi_url, result.error or "request failed")
        return {}

    try:
        payload = json.loads(result.text or "{}")
    except json.JSONDecodeError as exc:
        logger.warning("OpenAlex OA resolver returned invalid JSON for DOI %s: %s", doi_url, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _candidate_priority(candidate: OALocationCandidate, source_key: str) -> tuple[int, int, int, int, str]:
    if source_key in EXTERNAL_FIRST_SOURCES:
        external_preference = 0 if looks_like_publisher_location(candidate, source_key) else 1
    else:
        external_preference = 0
    return (
        external_preference,
        1 if candidate.pdf_url else 0,
        VERSION_PRIORITY.get(candidate.version, 0),
        1 if candidate.is_best_oa else 0,
        candidate.source_display_name.lower(),
    )


def _doi_url(doi: str) -> str:
    normalized = str(doi or "").strip()
    if not normalized:
        return ""
    if normalized.lower().startswith("https://doi.org/"):
        return normalized
    return f"https://doi.org/{normalized}"


def _hostname(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).hostname or ""


def _reconstruct_abstract(abstract_inverted_index: dict) -> str:
    if not isinstance(abstract_inverted_index, dict) or not abstract_inverted_index:
        return ""

    positions: dict[int, str] = {}
    for token, raw_positions in abstract_inverted_index.items():
        if not isinstance(token, str):
            continue
        if not isinstance(raw_positions, list):
            continue
        for pos in raw_positions:
            if isinstance(pos, int) and pos not in positions:
                positions[pos] = token

    if not positions:
        return ""

    return " ".join(token for _, token in sorted(positions.items()))
