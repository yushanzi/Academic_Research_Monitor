import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from sources.acs_source import ACS_FEEDS, ACSSource
from sources.arxiv_source import ArxivSource
from sources.base import BROWSER_HEADERS
from sources.biorxiv_source import BIORXIV_API, BiorxivSource

ARXIV_USER_AGENT = BROWSER_HEADERS["User-Agent"]
BIORXIV_USER_AGENT = BROWSER_HEADERS["User-Agent"]


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

    def test_acs_source_includes_jctc_feed_and_defaults(self):
        self.assertIn("jctcce", ACS_FEEDS)
        self.assertEqual(
            ACS_FEEDS["jctcce"]["name"],
            "Journal of Chemical Theory and Computation",
        )
        self.assertIn("jc=jctcce", ACS_FEEDS["jctcce"]["url"])
        self.assertEqual(ACS_FEEDS["jctcce"]["crossref_issn"], "1549-9618")

        source = ACSSource()
        self.assertIn("jctcce", source.journals)

    def test_acs_source_falls_back_to_crossref_when_feed_is_empty(self):
        today = datetime.now(timezone.utc).date().isoformat()
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Machine Learning Force Fields for Composite Polymer Electrolytes"],
                        "abstract": "<jats:p>Machine learning force fields improve polymer electrolyte modeling.</jats:p>",
                        "DOI": "10.1021/acs.jctc.6c01183",
                        "URL": "https://doi.org/10.1021/acs.jctc.6c01183",
                        "author": [
                            {"given": "Ada", "family": "Lovelace"},
                            {"given": "Grace", "family": "Hopper"},
                        ],
                        "published-online": {"date-parts": [[2026, 10, 9]]},
                    }
                ]
            }
        }
        crossref_response = Mock()
        crossref_response.text = json.dumps(payload)

        source = ACSSource(journals=["jctcce"])
        with patch.object(source, "_parse_feed", return_value=[]):
            with patch.object(source, "_fetch_phase", return_value=crossref_response) as mock_fetch:
                papers = source.fetch_papers(["polymer electrolyte"], 24 * 60)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1021/acs.jctc.6c01183")
        self.assertEqual(papers[0].authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertIn("Machine learning force fields improve polymer electrolyte modeling.", papers[0].abstract)
        self.assertIn("api.crossref.org/journals/1549-9618/works", mock_fetch.call_args.args[0])
        self.assertIn("from-pub-date", mock_fetch.call_args.args[0])
        self.assertEqual(mock_fetch.call_args.kwargs["headers"]["Accept"], "application/json")

    def test_acs_source_crossref_fallback_skips_items_outside_cutoff(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Old paper"],
                        "abstract": "<jats:p>Old abstract</jats:p>",
                        "DOI": "10.1021/acs.jctc.old",
                        "URL": "https://doi.org/10.1021/acs.jctc.old",
                        "published-online": {"date-parts": [[2026, 1, 1]]},
                    }
                ]
            }
        }
        crossref_response = Mock()
        crossref_response.text = json.dumps(payload)

        source = ACSSource(journals=["jctcce"])
        with patch.object(source, "_parse_feed", return_value=[]):
            with patch.object(source, "_fetch_phase", return_value=crossref_response):
                papers = source.fetch_papers(["old abstract"], 24)

        self.assertEqual(papers, [])

    def test_acs_source_crossref_fallback_uses_openalex_abstract_when_crossref_abstract_missing(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Machine Learning Force Fields for Composite Polymer Electrolytes"],
                        "DOI": "10.1021/acs.jctc.6c01183",
                        "URL": "https://doi.org/10.1021/acs.jctc.6c01183",
                        "published-online": {"date-parts": [[2026, 10, 9]]},
                    }
                ]
            }
        }
        crossref_response = Mock()
        crossref_response.text = json.dumps(payload)

        source = ACSSource(journals=["jctcce"])
        with patch.object(source, "_parse_feed", return_value=[]):
            with patch.object(source, "_fetch_phase", return_value=crossref_response):
                with patch("sources.acs_source.resolve_openalex_abstract", return_value="Machine learning force fields improve polymer electrolyte modeling."):
                    papers = source.fetch_papers(["polymer electrolyte"], 24 * 60)

        self.assertEqual(len(papers), 1)
        self.assertIn("polymer electrolyte modeling", papers[0].abstract)
