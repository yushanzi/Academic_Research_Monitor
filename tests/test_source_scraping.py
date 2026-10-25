import unittest
from unittest.mock import Mock, patch

from sources.base import scrape_html_with_retries


class SourceScrapingHelperTests(unittest.TestCase):
    def test_scrape_html_retries_retryable_status_then_succeeds(self):
        response = Mock()
        response.status_code = 200
        response.text = "<html>ok</html>"
        response.content = response.text.encode("utf-8")
        response.url = "https://example.com/paper"
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.raise_for_status.return_value = None

        retryable = Mock()
        retryable.status_code = 503
        retryable.text = ""
        retryable.content = b""
        retryable.url = "https://example.com/paper"
        retryable.headers = {}

        with patch("sources.base.requests.get", side_effect=[retryable, response]) as mock_get:
            with patch("sources.base.time.monotonic", return_value=0.0):
                with patch("sources.base.time.sleep") as mock_sleep:
                    result = scrape_html_with_retries(
                        "https://example.com/paper",
                        deadline_monotonic=999999.0,
                        context="test scrape",
                    )

        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.text, response.text)
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

    def test_scrape_html_does_not_treat_rate_limited_response_as_success_on_last_attempt(self):
        rate_limited = Mock()
        rate_limited.status_code = 429
        rate_limited.text = "rate limited"
        rate_limited.content = b"rate limited"
        rate_limited.url = "https://example.com/paper"
        rate_limited.headers = {}

        failed_browser_result = Mock(
            ok=False,
            error="blocked",
            used_browser_fallback=True,
            blocked=False,
            rate_limited=False,
            challenge_detected=False,
            status_code=None,
            text="",
            content=b"",
            headers={},
            method="browser",
            url="https://example.com/paper",
        )
        failed_browser_result.as_response.return_value = None
        with patch("sources.base.requests.get", side_effect=[rate_limited, rate_limited, rate_limited]):
            with patch("sources.base._playwright_fetch", return_value=failed_browser_result):
                result = scrape_html_with_retries(
                    "https://example.com/paper",
                    context="test scrape",
                )

        self.assertIsNone(result)

    def test_fetch_result_preserves_rate_limited_status_when_browser_fallback_fails(self):
        rate_limited = Mock()
        rate_limited.status_code = 429
        rate_limited.text = "rate limited"
        rate_limited.content = b"rate limited"
        rate_limited.url = "https://example.com/paper"
        rate_limited.headers = {}

        failed_browser_result = Mock(
            ok=False,
            error="playwright unavailable",
            used_browser_fallback=True,
            blocked=False,
            rate_limited=False,
            challenge_detected=False,
            status_code=None,
            text="",
            content=b"",
            headers={},
            method="browser",
            url="https://example.com/paper",
        )
        with patch("sources.base.requests.get", side_effect=[rate_limited]):
            with patch("sources.base._playwright_fetch", return_value=failed_browser_result):
                result = self._call_fetch_url_with_retries("https://example.com/paper")

        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 429)
        self.assertTrue(result.rate_limited)
        self.assertTrue(result.blocked)
        self.assertTrue(result.used_browser_fallback)
        self.assertIn("HTTP 429", result.error)
        self.assertIn("browser_fallback=playwright unavailable", result.error)

    def _call_fetch_url_with_retries(self, url: str):
        from sources.base import fetch_url_with_retries

        return fetch_url_with_retries(url, max_attempts=1, context="test scrape")
