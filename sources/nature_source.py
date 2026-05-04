from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from models import Paper
from .base import PaperSource, build_paper, matches_topics, scrape_html_with_retries

logger = logging.getLogger(__name__)

NATURE_RSS = "https://www.nature.com/{journal}.rss"
HEADERS = {
    "User-Agent": "AcademicResearchMonitor/1.0 (+local deployment)"
}
SCRAPE_BUDGET_SECONDS = 45


class NatureSource(PaperSource):
    name = "Nature"

    def __init__(self, journals: list[str] | None = None):
        self.journals = journals or ["nature"]

    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        cutoff = self._cutoff_time(hours)
        papers = []
        deadline_monotonic = time.monotonic() + SCRAPE_BUDGET_SECONDS

        for journal in self.journals:
            try:
                url = NATURE_RSS.format(journal=journal)
                batch = self._parse_feed(url, topics, cutoff, deadline_monotonic)
                papers.extend(batch)
                logger.info("Nature (%s): found %s papers", journal, len(batch))
            except Exception as e:
                logger.error("Nature (%s): error: %s", journal, e)

        return papers

    def _parse_feed(
        self,
        feed_url: str,
        topics: list[str],
        cutoff: datetime,
        deadline_monotonic: float,
    ) -> list[Paper]:
        feed = feedparser.parse(feed_url)
        papers = []

        for entry in feed.entries:
            # Parse publication date
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

            # Check topic relevance with title + RSS description
            if not matches_topics(f"{title} {description}", topics):
                continue

            # Try to scrape full abstract from article page
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
                    source="Nature",
                    doi=doi,
                )
            )

        return papers

    def _scrape_abstract(self, url: str, deadline_monotonic: float) -> str:
        """Scrape abstract from Nature article page via meta tags."""
        try:
            resp = scrape_html_with_retries(
                url,
                headers=HEADERS,
                deadline_monotonic=deadline_monotonic,
                context="Nature abstract scrape",
            )
            if not resp:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try standard meta tags first
            for attr in ("dc.description", "description", "citation_abstract"):
                meta = soup.find("meta", attrs={"name": attr})
                if meta and meta.get("content"):
                    return meta["content"].strip()

            # Try og:description
            meta = soup.find("meta", attrs={"property": "og:description"})
            if meta and meta.get("content"):
                return meta["content"].strip()

            # Try article abstract section
            abstract_div = soup.find("div", id="Abs1")
            if abstract_div:
                return abstract_div.get_text(strip=True)

        except Exception as e:
            logger.warning("Nature: failed to scrape abstract from %s: %s", url, e)
        return ""
