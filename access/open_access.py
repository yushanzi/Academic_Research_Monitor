from __future__ import annotations

import logging
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup

from .base import DocumentAccessProvider
from .pdf_extract import extract_text_from_pdf_bytes
from models import AccessInfo, Paper

logger = logging.getLogger(__name__)

# Unified browser-mimicking headers (imported from base for the fallback path)
HEADERS = {
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

IMPERSONATE = "chrome124"

GENERIC_FULL_TEXT_SELECTORS = (
    "article",
    "main",
    "div.c-article-body",
    "div.article__body",
    "section#Abs1-content",
    "section#bodymatter",
    "section.article__body",
    "div.article-body__full-view",
    "div.article__sections",
    "div#maincontent",
)
SOURCE_RULES = {
    "arxiv": {
        "pdf_patterns": ("/pdf/", ".pdf"),
        "full_text_selectors": ("article", "main"),
        "abstract_selectors": ("blockquote.abstract",),
        "meta_names": ("citation_abstract", "description", "dc.description"),
        "min_length": 1200,
        "min_length_short": 500,
    },
    "biorxiv": {
        "pdf_patterns": (".full.pdf", "/content/", ".pdf"),
        "full_text_selectors": ("div.section", "main", "article"),
        "abstract_selectors": ("div.section.abstract", "div#abstract-1", "section.abstract"),
        "meta_names": ("citation_abstract", "description", "dc.description"),
        "min_length": 1200,
        "min_length_short": 500,
    },
    "nature": {
        "pdf_patterns": (".pdf", "/pdf", "pdf"),
        "full_text_selectors": (
            "div.c-article-body",
            "div.main-content",
            "article section",
            "main",
        ),
        "abstract_selectors": ("div#Abs1-content", "section#Abs1-content", "section#abstract"),
        "meta_names": ("dc.description", "description", "citation_abstract"),
        "min_length": 1800,
        "min_length_short": 800,
    },
    "science": {
        "pdf_patterns": (".pdf", "/doi/pdf", "/pdf/"),
        "full_text_selectors": (
            "div.article__body",
            "section.article__body",
            "main",
        ),
        "abstract_selectors": ("section#abstract", "div.article__abstract", "div.hlFld-Abstract"),
        "meta_names": ("citation_abstract", "dc.description", "description"),
        "min_length": 1800,
        "min_length_short": 800,
    },
    "acs": {
        "pdf_patterns": (".pdf", "/doi/pdf", "/pdf/"),
        "full_text_selectors": (
            "div.article_content",
            "div.article__body",
            "main",
        ),
        "abstract_selectors": ("div.article_abstract-content", "section.abstract", "div#abstractBox"),
        "meta_names": ("dc.Description", "dc.description", "citation_abstract"),
        "min_length": 1800,
        "min_length_short": 800,
    },
}


class OpenAccessDocumentAccessProvider(DocumentAccessProvider):
    def resolve(self, paper: Paper) -> AccessInfo:
        source_key = _source_key(paper)
        rules = SOURCE_RULES.get(source_key, {})

        doi_url = _doi_url(paper.doi)
        landing_page_url = paper.landing_page_url or paper.url or doi_url
        entry_url = paper.entry_url or landing_page_url or doi_url
        download_url = paper.download_url or paper.pdf_url or _source_pdf_fallback(paper, source_key)
        open_access = bool(download_url)
        full_text = ""
        full_text_available = False
        evidence_level = "abstract_only"
        effective_access_mode = "open_access" if download_url else "abstract_only"

        fetched_response = None
        if landing_page_url:
            fetched_response = _safe_get(landing_page_url)
        if not fetched_response and doi_url and doi_url != landing_page_url:
            fetched_response = _safe_get(doi_url)
            if fetched_response:
                landing_page_url = fetched_response.url
                entry_url = entry_url or landing_page_url

        if fetched_response and _is_html(fetched_response):
            resolved_landing, resolved_entry, resolved_download, extracted_text = _parse_landing_page(
                fetched_response.url,
                fetched_response.text,
                paper,
                rules,
                source_key,
            )
            landing_page_url = resolved_landing or landing_page_url
            entry_url = resolved_entry or entry_url or landing_page_url or doi_url
            if resolved_download and not download_url:
                download_url = resolved_download
            if extracted_text:
                full_text = extracted_text
                full_text_available = True
                evidence_level = "full_text"
                effective_access_mode = "open_access"
                open_access = True

        if not full_text_available and download_url:
            extracted_text = _extract_full_text_from_pdf(download_url, paper, rules)
            if extracted_text:
                full_text = extracted_text
                full_text_available = True
                evidence_level = "full_text"
                effective_access_mode = "open_access"
                open_access = True

        if not entry_url:
            entry_url = doi_url
        if download_url:
            open_access = True
            if effective_access_mode == "abstract_only":
                effective_access_mode = "open_access"

        return AccessInfo(
            landing_page_url=landing_page_url or "",
            entry_url=entry_url or "",
            download_url=download_url,
            full_text_available=full_text_available,
            full_text=full_text,
            open_access=open_access,
            effective_access_mode=effective_access_mode,
            evidence_level=evidence_level,
        )


def _source_key(paper: Paper) -> str:
    source = (paper.source or "").lower()
    if "arxiv" in source:
        return "arxiv"
    if "biorxiv" in source:
        return "biorxiv"
    if "nature" in source:
        return "nature"
    if "science" in source:
        return "science"
    if "acs" in source:
        return "acs"
    return "generic"


def _doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    return f"https://doi.org/{doi}" if doi else ""


# ---------------------------------------------------------------------------
# HTTP helpers — curl_cffi with browser impersonation, Playwright fallback
# ---------------------------------------------------------------------------


def _curl_fetch(url: str) -> requests.Response | None:
    """Fetch via curl_cffi with browser TLS fingerprint."""
    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            impersonate=IMPERSONATE,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp
    except Exception as exc:
        logger.debug("curl_cffi fetch failed for %s: %s", url, exc)
        return None


def _is_cloudflare_block(response) -> bool:
    """Detect Cloudflare challenge / block page."""
    if response is None:
        return False
    status = getattr(response, "status_code", 0)
    if status not in (403, 503):
        return False
    text = (getattr(response, "text", "") or "").lower()
    markers = (
        "cf-browser-verification", "cf-challenge", "cloudflare",
        "checking your browser", "just a moment", "turnstile",
    )
    if any(m in text for m in markers):
        return True
    headers_lower = {k.lower(): v.lower() for k, v in (getattr(response, "headers", {}) or {}).items()}
    if headers_lower.get("server") == "cloudflare":
        return True
    if headers_lower.get("cf-ray"):
        return True
    return False


def _playwright_fetch(url: str, timeout_ms: int = 20000) -> str | None:
    """Fetch page HTML via headless Chromium (handles Cloudflare challenges)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; browser fallback unavailable")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)  # Allow Cloudflare challenge to complete
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return None


class _BrowserResponse:
    """Minimal response-like object wrapping browser-fetched HTML."""

    def __init__(self, text: str, url: str, status_code: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"Browser fetch HTTP {self.status_code}")


def _safe_get(url: str):
    """Fetch *url*, falling back from curl_cffi → headless browser."""
    # Try curl_cffi first (fast, lightweight)
    response = _curl_fetch(url)
    if response is not None and not _is_cloudflare_block(response):
        return response

    if response is not None and _is_cloudflare_block(response):
        logger.info("Cloudflare block detected for %s; switching to headless browser", url)

    # Fall back to headless browser
    html = _playwright_fetch(url)
    if html is None:
        logger.debug("Failed to fetch access candidate %s (all methods exhausted)", url)
        return None

    return _BrowserResponse(html, url)


# ---------------------------------------------------------------------------
# Remaining helpers (unchanged logic)
# ---------------------------------------------------------------------------


def _extract_full_text_from_pdf(download_url: str, paper: Paper, rules: dict) -> str:
    response = _safe_get(download_url)
    if not response:
        return ""
    if not _is_pdf_response(response, download_url):
        logger.debug("Skipping non-PDF download URL for full-text extraction: %s", download_url)
        return ""

    extracted_text = extract_text_from_pdf_bytes(getattr(response, "content", b"") or b"")
    if _meets_text_threshold(extracted_text, paper, rules):
        return extracted_text[:20000]
    return ""


def _is_html(response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    return "html" in content_type or "xml" in content_type or not content_type


def _is_pdf_response(response, url: str) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    final_url = str(getattr(response, "url", "") or url).lower()
    requested_url = str(url or "").lower()
    return "pdf" in content_type or final_url.endswith(".pdf") or requested_url.endswith(".pdf")


def _parse_landing_page(
    base_url: str,
    html: str,
    paper: Paper,
    rules: dict,
    source_key: str,
) -> tuple[str, str, str, str]:
    soup = BeautifulSoup(html, "html.parser")
    landing_page_url = base_url
    entry_url = _select_entry_url(base_url, soup, paper)
    download_url = _find_pdf_url(base_url, soup, paper, rules, source_key)
    full_text = _extract_full_text_from_html(soup, paper, rules, source_key)
    return landing_page_url, entry_url, download_url, full_text


def _select_entry_url(base_url: str, soup: BeautifulSoup, paper: Paper) -> str:
    for attr in (
        ("meta", {"property": "og:url"}, "content"),
        ("meta", {"name": "citation_public_url"}, "content"),
    ):
        tag = soup.find(attr[0], attrs=attr[1])
        if tag and tag.get(attr[2]):
            return urljoin(base_url, tag[attr[2]].strip())
    return paper.entry_url or paper.landing_page_url or base_url


def _find_pdf_url(base_url: str, soup: BeautifulSoup, paper: Paper, rules: dict, source_key: str) -> str:
    for name in ("citation_pdf_url", "wkhealth_pdf_url", "pdf_url"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())

    for prop in ("og:pdf", "og:pdf_url"):
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())

    patterns = rules.get("pdf_patterns") or (".pdf", "/pdf")
    anchor = soup.find("a", href=lambda href: href and any(hint in href.lower() for hint in patterns))
    if anchor and anchor.get("href"):
        return urljoin(base_url, anchor["href"].strip())

    return paper.download_url or paper.pdf_url or _source_pdf_fallback(paper, source_key)


def _source_pdf_fallback(paper: Paper, source_key: str) -> str:
    url = paper.url or paper.landing_page_url or ""
    doi = paper.doi.strip()

    if source_key == "arxiv" and "/abs/" in url:
        return url.replace("/abs/", "/pdf/") + ".pdf"
    if source_key == "biorxiv" and doi:
        return f"https://www.biorxiv.org/content/{doi}v1.full.pdf"
    if source_key == "science" and doi:
        return f"https://www.science.org/doi/pdf/{doi}"
    if source_key == "acs" and doi:
        return f"https://pubs.acs.org/doi/pdf/{doi}"
    return ""


def _extract_full_text_from_html(soup: BeautifulSoup, paper: Paper, rules: dict, source_key: str) -> str:
    selectors = tuple(rules.get("full_text_selectors") or ()) + GENERIC_FULL_TEXT_SELECTORS
    seen = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        container = soup.select_one(selector)
        if container:
            if _looks_like_abstract_container(container):
                continue
            text = _normalize_text("\n".join(p.get_text(" ", strip=True) for p in container.find_all("p")))
            if _meets_text_threshold(text, paper, rules):
                return text[:20000]

    paragraphs = _normalize_text("\n".join(_non_abstract_paragraphs(soup)))
    if _meets_text_threshold(paragraphs, paper, rules):
        return paragraphs[:20000]

    return ""


def _extract_abstract_like_text(soup: BeautifulSoup, rules: dict) -> str:
    meta_candidates = []
    meta_names = tuple(rules.get("meta_names") or ()) + (
        "citation_abstract",
        "dc.description",
        "description",
    )
    seen = set()
    for name in meta_names:
        if name in seen:
            continue
        seen.add(name)
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            meta_candidates.append(tag["content"].strip())
    tag = soup.find("meta", attrs={"property": "og:description"})
    if tag and tag.get("content"):
        meta_candidates.append(tag["content"].strip())
    if meta_candidates:
        return _normalize_text(" ".join(meta_candidates))

    selectors = tuple(rules.get("abstract_selectors") or ()) + (
        "section#abstract",
        "div#Abs1",
        "div.article__abstract",
        "section.abstract",
    )
    seen = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        container = soup.select_one(selector)
        if container:
            return _normalize_text(container.get_text(" ", strip=True))
    return ""


def _meets_text_threshold(text: str, paper: Paper, rules: dict, *, allow_short: bool = False) -> bool:
    if not text:
        return False
    source = _source_key(paper)
    min_length = rules.get("min_length", 2000)
    short_length = rules.get("min_length_short", min_length)
    if allow_short and source in {"arxiv", "biorxiv"}:
        min_length = short_length
    return len(text) >= min_length


def _looks_like_abstract_container(container) -> bool:
    attrs = []
    if container.get("id"):
        attrs.append(container.get("id"))
    attrs.extend(container.get("class") or [])
    if container.get("data-title"):
        attrs.append(container.get("data-title"))
    label = " ".join(str(value).lower() for value in attrs if value)
    if "abstract" in label:
        return True
    return container.name == "blockquote" and "abstract" in label


def _non_abstract_paragraphs(soup: BeautifulSoup) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in soup.find_all("p"):
        if any(_looks_like_abstract_container(parent) for parent in paragraph.parents if getattr(parent, "name", None)):
            continue
        text = paragraph.get_text(" ", strip=True)
        if text:
            paragraphs.append(text)
    return paragraphs


def _normalize_text(text: str) -> str:
    return " ".join(text.split())
