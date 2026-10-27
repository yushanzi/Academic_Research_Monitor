import json
import unittest
from unittest.mock import Mock, patch

from access.oa_resolver import resolve_open_access_locations, resolve_openalex_abstract


def _fetch_result(response=None, *, ok=True, error=""):
    result = Mock()
    result.ok = ok
    result.error = error
    result.text = response.text if response is not None else ""
    return result


class OAResolverTests(unittest.TestCase):
    def test_resolve_open_access_locations_prioritizes_external_candidates_for_science(self):
        payload = {
            "best_oa_location": {
                "is_oa": True,
                "landing_page_url": "https://www.science.org/doi/10.1126/science.abc123",
                "pdf_url": "https://www.science.org/doi/pdf/10.1126/science.abc123",
                "version": "publishedVersion",
                "source": {"display_name": "Science", "type": "journal"},
            },
            "locations": [
                {
                    "is_oa": True,
                    "landing_page_url": "https://repository.example.org/record/abc123",
                    "pdf_url": "https://repository.example.org/abc123.pdf",
                    "version": "publishedVersion",
                    "source": {"display_name": "Institutional Repository", "type": "repository"},
                }
            ],
        }
        response = Mock()
        response.text = json.dumps(payload)

        with patch("access.oa_resolver.fetch_url_with_retries", return_value=_fetch_result(response)):
            candidates = resolve_open_access_locations("10.1126/science.abc123", source_key="science")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].landing_page_url, "https://repository.example.org/record/abc123")
        self.assertEqual(candidates[1].landing_page_url, "https://www.science.org/doi/10.1126/science.abc123")

    def test_resolve_open_access_locations_ignores_invalid_payloads(self):
        response = Mock()
        response.text = "{not json"

        with patch("access.oa_resolver.fetch_url_with_retries", return_value=_fetch_result(response)):
            candidates = resolve_open_access_locations("10.1126/science.abc123", source_key="science")

        self.assertEqual(candidates, [])

    def test_resolve_openalex_abstract_reconstructs_inverted_index(self):
        payload = {
            "abstract_inverted_index": {
                "Machine": [0],
                "learning": [1],
                "helps": [2],
                "chemistry": [3],
            }
        }
        response = Mock()
        response.text = json.dumps(payload)

        with patch("access.oa_resolver.fetch_url_with_retries", return_value=_fetch_result(response)):
            abstract = resolve_openalex_abstract("10.1021/acs.jctc.6c01183")

        self.assertEqual(abstract, "Machine learning helps chemistry")
