import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from sources.arxiv_source import ArxivSource, USER_AGENT as ARXIV_USER_AGENT
from sources.biorxiv_source import BIORXIV_API, BiorxivSource, USER_AGENT as BIORXIV_USER_AGENT


class SourceTests(unittest.TestCase):
    def test_arxiv_search_uses_descriptive_user_agent_and_returns_paper(self):
        published = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/1234.5678</id>
            <published>{published}</published>
            <title> Test Paper </title>
            <summary> Test abstract </summary>
            <author><name>Author A</name></author>
            <link href="https://arxiv.org/abs/1234.5678" type="text/html" />
            <link href="https://arxiv.org/pdf/1234.5678.pdf" type="application/pdf" title="pdf" />
            <arxiv:doi>10.1000/test</arxiv:doi>
          </entry>
        </feed>
        """.format(published=published)
        response = Mock(text=xml)
        response.raise_for_status.return_value = None

        with patch("sources.arxiv_source.requests.get", return_value=response) as mock_get:
            papers = ArxivSource().fetch_papers(["protein folding"], 48)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "Test Paper")
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["User-Agent"],
            ARXIV_USER_AGENT,
        )

    def test_biorxiv_fetch_uses_descriptive_user_agent(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {
                "collection": [
                    {
                        "title": "Protein folding study",
                        "abstract": "Protein folding abstract",
                        "date": today,
                        "authors": "Author A; Author B",
                        "doi": "10.1101/2026.03.30.123456",
                    }
                ],
                "messages": [{"total": "1"}],
            }
        ]

        with patch("sources.biorxiv_source.requests.get", return_value=response) as mock_get:
            papers = BiorxivSource().fetch_papers(["protein folding"], 24)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["Author A", "Author B"])
        self.assertTrue(mock_get.call_args.args[0].startswith(BIORXIV_API))
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["User-Agent"],
            BIORXIV_USER_AGENT,
        )
