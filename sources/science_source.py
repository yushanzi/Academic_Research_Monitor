import logging
import time
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from models import Paper
from .base import PaperSource, build_paper, matches_topics, scrape_html_with_retries

logger = logging.getLogger(__name__)

SCIENCE_RSS = "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"
HEADERS = {
    "User-Agent": "AcademicResearchMonitor/1.0 (+local deployment)"
}
SCRAPE_BUDGET_SECONDS = 45


class ScienceSource(PaperSource):
    name = "Science"

    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        cutoff = self._cutoff_time(hours)
        papers = []
        deadline_monotonic = time.monotonic() + SCRAPE_BUDGET_SECONDS

        try:
            feed = feedparser.parse(SCIENCE_RSS)
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
                        source="Science",
                        doi=doi,
                    )
                )

            logger.info("Science: found %s papers", len(papers))
        except Exception as e:
            logger.error("Science: error fetching feed: %s", e)

        return papers

    def _scrape_abstract(self, url: str, deadline_monotonic: float) -> str:
        """Scrape abstract from Science article page."""
        try:
            resp = scrape_html_with_retries(
                url,
                headers=HEADERS,
                deadline_monotonic=deadline_monotonic,
                context="Science abstract scrape",
            )
            if not resp:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")

            for attr in ("citation_abstract", "dc.description", "description"):
                meta = soup.find("meta", attrs={"name": attr})
                if meta and meta.get("content"):
                    return meta["content"].strip()

            meta = soup.find("meta", attrs={"property": "og:description"})
            if meta and meta.get("content"):
                return meta["content"].strip()

            abstract_section = soup.find("section", id="abstract")
            if abstract_section:
                return abstract_section.get_text(strip=True)

        except Exception as e:
            logger.warning("Science: failed to scrape abstract from %s: %s", url, e)
        return ""
