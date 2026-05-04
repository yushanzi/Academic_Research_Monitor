import unittest
from unittest.mock import Mock, patch

import requests

from sources.base import scrape_html_with_retries


class SourceScrapingHelperTests(unittest.TestCase):
    def test_scrape_html_retries_retryable_status_then_succeeds(self):
        retryable = requests.HTTPError("retryable")
        retryable.response = Mock(status_code=503)

        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None

        with patch("sources.base.requests.get", side_effect=[retryable, response]) as mock_get:
            with patch("sources.base.time.monotonic", return_value=0.0):
                with patch("sources.base.time.sleep") as mock_sleep:
                    result = scrape_html_with_retries(
                        "https://example.com/paper",
                        deadline_monotonic=999999.0,
                        context="test scrape",
                    )

        self.assertIs(result, response)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    def test_scrape_html_returns_none_when_budget_is_already_exhausted(self):
        with patch("sources.base.time.monotonic", return_value=10.0):
            with patch("sources.base.requests.get") as mock_get:
                result = scrape_html_with_retries(
                    "https://example.com/paper",
                    deadline_monotonic=10.0,
                    context="test scrape",
                )

        self.assertIsNone(result)
        mock_get.assert_not_called()
