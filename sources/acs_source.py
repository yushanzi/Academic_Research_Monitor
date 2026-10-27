from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
from bs4 import BeautifulSoup

from access.oa_resolver import resolve_openalex_abstract
from models import Paper
from .base import PublisherSource, build_paper, matches_topics

logger = logging.getLogger(__name__)

# Map journal codes to RSS feed URLs
ACS_FEEDS = {
    "jmcmar": {
        "name": "Journal of Medicinal Chemistry",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jmcmar",
        "crossref_issn": "0022-2623",
    },
    "jacsat": {
        "name": "JACS",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jacsat",
        "crossref_issn": "0002-7863",
    },
    "acbcct": {
        "name": "ACS Chemical Biology",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=acbcct",
        "crossref_issn": "1554-8929",
    },
    "jctcce": {
        "name": "Journal of Chemical Theory and Computation",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jctcce",
        "crossref_issn": "1549-9618",
    },
}

SCRAPE_BUDGET_SECONDS = 45
CROSSREF_WORKS_API = "https://api.crossref.org/journals/{issn}/works"
CROSSREF_ROWS = 50


class ACSSource(PublisherSource):
    name = "ACS Publications"

    def __init__(
        self,
        journals: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.journals = journals or ["jmcmar", "jacsat", "jctcce"]

    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        cutoff = self._cutoff_time(hours)
        papers = []
        deadline_monotonic = time.monotonic() + SCRAPE_BUDGET_SECONDS

        for code in self.journals:
            info = ACS_FEEDS.get(code)
            if not info:
                logger.warning("ACS: unknown journal code '%s', skipping", code)
                continue
            try:
                batch = self._parse_feed(
                    info["url"],
                    info["name"],
                    topics,
                    cutoff,
                    deadline_monotonic,
                )
                if not batch:
                    logger.info("ACS (%s): feed returned no usable papers; trying Crossref discovery fallback", info["name"])
                    batch = self._fetch_crossref_batch(
                        info,
                        topics,
                        cutoff,
                        deadline_monotonic,
                    )
                papers.extend(batch)
                logger.info("ACS (%s): found %s papers", info["name"], len(batch))
            except Exception as e:
                logger.error("ACS (%s): error: %s", info["name"], e)

        return papers

    def _parse_feed(
        self,
        feed_url: str,
        journal_name: str,
        topics: list[str],
        cutoff: datetime,
        deadline_monotonic: float,
    ) -> list[Paper]:
        feed_response = self._fetch_phase(
            feed_url,
            phase="discovery",
            allow_browser=False,
            expect_html=False,
            deadline_monotonic=deadline_monotonic,
            context=f"ACS feed fetch ({journal_name})",
        )
        if not feed_response:
            return []
        feed = feedparser.parse(feed_response.text)
        papers = []

        for entry in feed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            if not published or published < cutoff:
                continue

            title = entry.get("title", "")
            description = entry.get("summary", "")
            link = entry.get("link", "")

            if not matches_topics(f"{title} {description}", topics):
                continue

            abstract = description
            if link and not self.feed_only:
                scraped_abstract = self._scrape_abstract(link, deadline_monotonic)
                if scraped_abstract:
                    abstract = scraped_abstract
            if not abstract:
                abstract = description

            authors = []
            if hasattr(entry, "authors"):
                authors = [a.get("name", "") for a in entry.authors if a.get("name")]

            doi = ""
            if hasattr(entry, "prism_doi"):
                doi = entry.prism_doi
            elif "doi.org" in link:
                doi = link.split("doi.org/")[-1]

            papers.append(
                build_paper(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    date=published.strftime("%Y-%m-%d"),
                    url=link,
                    source=f"ACS - {journal_name}",
                    doi=doi,
                    discovery_method="rss",
                )
            )

        return papers

    def _fetch_crossref_batch(
        self,
        info: dict,
        topics: list[str],
        cutoff: datetime,
        deadline_monotonic: float,
    ) -> list[Paper]:
        issn = str(info.get("crossref_issn", "")).strip()
        if not issn:
            logger.warning("ACS (%s): no Crossref ISSN configured; skipping Crossref fallback", info["name"])
            return []

        today = datetime.now(timezone.utc).date().isoformat()
        params = {
            "filter": f"from-pub-date:{cutoff.date().isoformat()},until-pub-date:{today},type:journal-article",
            "rows": CROSSREF_ROWS,
        }
        url = f"{CROSSREF_WORKS_API.format(issn=issn)}?{urlencode(params)}"
        response = self._fetch_phase(
            url,
            phase="discovery",
            headers={"Accept": "application/json"},
            allow_browser=False,
            expect_html=False,
            deadline_monotonic=deadline_monotonic,
            context=f"ACS Crossref discovery ({info['name']})",
        )
        if not response:
            return []

        try:
            payload = json.loads(response.text or "{}")
        except json.JSONDecodeError as exc:
            logger.warning("ACS (%s): invalid Crossref JSON: %s", info["name"], exc)
            return []

        papers = []
        items = (payload.get("message") or {}).get("items") or []
        for item in items:
            published = _crossref_published_datetime(item)
            if not published or published < cutoff:
                continue

            title = _clean_crossref_text(_first(item.get("title")))
            doi = str(item.get("DOI", "")).strip()
            abstract = _clean_crossref_abstract(item.get("abstract"))
            if not abstract and doi:
                abstract = resolve_openalex_abstract(doi, proxy_url=self._resolve_proxy_url())
            link = str(item.get("URL", "")).strip()
            text = f"{title} {abstract}"
            if not matches_topics(text, topics):
                continue

            papers.append(
                build_paper(
                    title=title,
                    authors=_crossref_authors(item),
                    abstract=abstract,
                    date=published.strftime("%Y-%m-%d"),
                    url=link or (f"https://doi.org/{doi}" if doi else ""),
                    source=f"ACS - {info['name']}",
                    doi=doi,
                    discovery_method="crossref",
                )
            )

        return papers

    def _scrape_abstract(self, url: str, deadline_monotonic: float) -> str:
        """Scrape abstract from ACS article page."""
        try:
            resp = self._fetch_phase(
                url,
                phase="metadata",
                deadline_monotonic=deadline_monotonic,
                context="ACS abstract scrape",
            )
            if not resp:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")

            for attr in ("dc.Description", "dc.description", "citation_abstract"):
                meta = soup.find("meta", attrs={"name": attr})
                if meta and meta.get("content"):
                    return meta["content"].strip()

            meta = soup.find("meta", attrs={"property": "og:description"})
            if meta and meta.get("content"):
                return meta["content"].strip()

        except Exception as e:
            logger.warning("ACS: failed to scrape abstract from %s: %s", url, e)
        return ""


def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _clean_crossref_text(value: str) -> str:
    if not value:
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())


def _clean_crossref_abstract(value) -> str:
    return _clean_crossref_text(_first(value))


def _crossref_authors(item: dict) -> list[str]:
    authors = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        given = str(author.get("given", "")).strip()
        family = str(author.get("family", "")).strip()
        name = " ".join(part for part in (given, family) if part)
        if name:
            authors.append(name)
    return authors


def _crossref_published_datetime(item: dict) -> datetime | None:
    for field in ("published-print", "published-online", "published"):
        raw = item.get(field) or {}
        date_parts = raw.get("date-parts") or []
        if not date_parts:
            continue
        parts = list(date_parts[0])
        if not parts:
            continue
        while len(parts) < 3:
            parts.append(1)
        try:
            return datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
