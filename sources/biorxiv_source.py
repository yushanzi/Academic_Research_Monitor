import logging
from datetime import datetime, timezone

import requests

from models import Paper
from .base import PaperSource, build_paper, matches_topics

logger = logging.getLogger(__name__)
USER_AGENT = "AcademicResearchMonitor/1.0 (+local deployment)"

BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"


class BiorxivSource(PaperSource):
    name = "bioRxiv"

    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        now = datetime.now(timezone.utc)
        cutoff = self._cutoff_time(hours)
        end_date = now.strftime("%Y-%m-%d")
        start_date = cutoff.strftime("%Y-%m-%d")

        if hours % 24 != 0:
            logger.warning(
                "bioRxiv API only exposes publication dates, so a %s-hour window is approximated at day precision",
                hours,
            )

        papers = []
        cursor = 0

        while True:
            try:
                url = f"{BIORXIV_API}/{start_date}/{end_date}/{cursor}"
                resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("bioRxiv: API error at cursor %s: %s", cursor, e)
                break

            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                title = item.get("title", "")
                abstract = item.get("abstract", "")
                text = f"{title} {abstract}"

                paper_date_str = item.get("date", "")
                try:
                    paper_date = datetime.strptime(paper_date_str, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning("bioRxiv: skipping paper with invalid date '%s'", paper_date_str)
                    continue

                if paper_date < cutoff.date() or paper_date > now.date():
                    continue

                if not matches_topics(text, topics):
                    continue

                authors = item.get("authors", "")
                if isinstance(authors, str):
                    authors = [a.strip() for a in authors.split(";") if a.strip()]

                doi = item.get("doi", "")
                papers.append(
                    build_paper(
                        title=title,
                        authors=authors,
                        abstract=abstract,
                        date=paper_date_str,
                        url=f"https://doi.org/{doi}" if doi else "",
                        source="bioRxiv",
                        doi=doi,
                    )
                )

            # Check if there are more pages
            messages = data.get("messages", [])
            total = 0
            for msg in messages:
                if "total" in msg:
                    total = int(msg["total"])
            cursor += len(collection)
            if cursor >= total:
                break

        logger.info("bioRxiv: found %s matching papers", len(papers))
        return papers
