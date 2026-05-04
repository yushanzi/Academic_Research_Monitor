from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from models import Paper
from .base import PaperSource, build_paper, matches_topics, scrape_html_with_retries

logger = logging.getLogger(__name__)

# Map journal codes to RSS feed URLs
ACS_FEEDS = {
    "jmcmar": {
        "name": "Journal of Medicinal Chemistry",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jmcmar",
    },
    "jacsat": {
        "name": "JACS",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=jacsat",
    },
    "acbcct": {
        "name": "ACS Chemical Biology",
        "url": "https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=acbcct",
    },
}

HEADERS = {
    "User-Agent": "AcademicResearchMonitor/1.0 (+local deployment)"
}
SCRAPE_BUDGET_SECONDS = 45


class ACSSource(PaperSource):
    name = "ACS Publications"

    def __init__(self, journals: list[str] | None = None):
        self.journals = journals or ["jmcmar", "jacsat"]

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
        feed = feedparser.parse(feed_url)
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

            abstract = self._scrape_abstract(link, deadline_monotonic) if link else description
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
                )
            )

        return papers

    def _scrape_abstract(self, url: str, deadline_monotonic: float) -> str:
        """Scrape abstract from ACS article page."""
        try:
            resp = scrape_html_with_retries(
                url,
                headers=HEADERS,
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
