import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from models import Paper
from .base import PaperSource, build_paper

logger = logging.getLogger(__name__)
USER_AGENT = "AcademicResearchMonitor/1.0 (+local deployment)"

ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivSource(PaperSource):
    name = "arXiv"

    def fetch_papers(self, topics: list[str], hours: int) -> list[Paper]:
        cutoff = self._cutoff_time(hours)
        papers = []

        for i, topic in enumerate(topics):
            if i > 0:
                time.sleep(3)  # arXiv rate limit: 1 request per 3 seconds
            try:
                batch = self._search_topic(topic, cutoff)
                papers.extend(batch)
                logger.info("arXiv: found %s papers for '%s'", len(batch), topic)
            except Exception as e:
                logger.error("arXiv: error searching '%s': %s", topic, e)

        return papers

    def _search_topic(self, topic: str, cutoff: datetime) -> list[Paper]:
        params = {
            "search_query": f'all:"{topic}"',
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": 50,
        }
        resp = requests.get(
            ARXIV_API,
            params=params,
            timeout=30,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        papers = []

        for entry in root.findall("atom:entry", ARXIV_NS):
            published_str = entry.findtext("atom:published", "", ARXIV_NS)
            if not published_str:
                continue
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            if published < cutoff:
                continue

            title = entry.findtext("atom:title", "", ARXIV_NS).strip()
            title = " ".join(title.split())  # normalize whitespace

            authors = [
                name.text.strip()
                for name in entry.findall("atom:author/atom:name", ARXIV_NS)
                if name.text
            ]

            abstract = entry.findtext("atom:summary", "", ARXIV_NS).strip()
            abstract = " ".join(abstract.split())

            # Get the abstract page link (not the PDF)
            url = ""
            pdf_url = ""
            for link in entry.findall("atom:link", ARXIV_NS):
                if link.get("type") == "text/html":
                    url = link.get("href", "")
                if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                    pdf_url = link.get("href", "")
            if not url:
                url = entry.findtext("atom:id", "", ARXIV_NS)

            doi = ""
            doi_elem = entry.find(
                "{http://arxiv.org/schemas/atom}doi"
            )
            if doi_elem is not None and doi_elem.text:
                doi = doi_elem.text.strip()

            papers.append(
                build_paper(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    date=published.strftime("%Y-%m-%d"),
                    url=url,
                    source="arXiv",
                    doi=doi,
                    pdf_url=pdf_url,
                )
            )

        return papers
