import unittest
from unittest.mock import Mock, patch

from sources.base import scrape_html_with_retries


class SourceScrapingHelperTests(unittest.TestCase):
    def test_scrape_html_treats_generic_403_forbidden_page_as_block(self):
        blocked = Mock()
        blocked.status_code = 200
        blocked.text = "<html><head><title>403 Forbidden</title></head><body>Access to this resource has been restricted due to unusual traffic from your network.</body></html>"
        blocked.content = blocked.text.encode("utf-8")
        blocked.url = "https://zenodo.org/records/123"
        blocked.headers = {"content-type": "text/html; charset=utf-8"}

        browser_result = Mock(
            ok=False,
            error="challenge page persisted",
            used_browser_fallback=True,
            blocked=True,
            rate_limited=False,
            challenge_detected=True,
            status_code=200,
            text=blocked.text,
            content=blocked.content,
            headers=blocked.headers,
            method="browser",
            url="https://zenodo.org/records/123",
        )
        browser_result.as_response.return_value = None

        with patch("sources.base.requests.get", return_value=blocked):
            with patch("sources.base._playwright_fetch", return_value=browser_result):
                result = self._call_fetch_url_with_retries("https://zenodo.org/records/123")

        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertTrue(result.challenge_detected)
        self.assertTrue(result.used_browser_fallback)

    def test_playwright_fetch_retries_with_plain_context_when_headered_context_never_stabilizes(self):
        class FakePage:
            def __init__(self, html: str | None):
                self._html = html
                self.url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"

            def goto(self, *args, **kwargs):
                return None

            def wait_for_timeout(self, *args, **kwargs):
                return None

            def content(self):
                if self._html is None:
                    raise Exception("Page.content: Unable to retrieve content because the page is navigating and changing the content.")
                return self._html

        class FakeContext:
            def __init__(self, html: str | None):
                self._html = html

            def new_page(self):
                return FakePage(self._html)

            def close(self):
                return None

        class FakeBrowser:
            def __init__(self):
                self._calls = 0

            def new_context(self, **kwargs):
                self._calls += 1
                if self._calls == 1:
                    self.first_kwargs = kwargs
                    return FakeContext(None)
                self.second_kwargs = kwargs
                return FakeContext("<html><article><p>resolved</p></article></html>")

            def close(self):
                return None

        class FakePlaywrightManager:
            def __init__(self, browser):
                self.chromium = Mock(launch=Mock(return_value=browser))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        browser = FakeBrowser()

        with patch("playwright.sync_api.sync_playwright", return_value=FakePlaywrightManager(browser)):
            from sources.base import _playwright_fetch

            result = _playwright_fetch("https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")

        self.assertTrue(result.ok)
        self.assertEqual(result.method, "browser")
        self.assertTrue(result.used_browser_fallback)
        self.assertIn("user_agent", browser.first_kwargs)
        self.assertEqual(browser.second_kwargs, {})

    def test_scrape_html_treats_cookie_challenge_page_as_block_and_uses_browser(self):
        challenge = Mock()
        challenge.status_code = 203
        challenge.text = "<html><body>Cookies must be enabled<script>const x = 'N_POW_Challenge';</script></body></html>"
        challenge.content = challenge.text.encode("utf-8")
        challenge.url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"
        challenge.headers = {"content-type": "text/html; charset=utf-8"}

        browser_result = Mock(
            ok=True,
            error="",
            used_browser_fallback=True,
            blocked=False,
            rate_limited=False,
            challenge_detected=False,
            status_code=200,
            text="<html><article><p>resolved</p></article></html>",
            content=b"<html><article><p>resolved</p></article></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            method="browser",
            url="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
        )
        browser_result.as_response.return_value = None

        with patch("sources.base.requests.get", return_value=challenge):
            with patch("sources.base._playwright_fetch", return_value=browser_result):
                result = self._call_fetch_url_with_retries("https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")

        self.assertTrue(result.ok)
        self.assertEqual(result.method, "browser")
        self.assertTrue(result.used_browser_fallback)

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
