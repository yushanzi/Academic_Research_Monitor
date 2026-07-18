"""
Headless-browser fetcher using Playwright.

Provides a simple synchronous API for fetching web pages through a real
Chromium browser.  This is the most robust way to get past Cloudflare and
similar bot-protection layers, because the TLS fingerprint, HTTP/2
behaviour, and JavaScript execution are identical to a real user's browser.

Usage::

    from sources.browser_fetcher import browser_fetch

    html = browser_fetch("https://www.biorxiv.org/content/10.1101/...v1")
    if html is None:
        print("Failed to fetch the page")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT_MS = 30_000
CLOUDFLARE_WAIT_MS = 5_000  # extra wait for Cloudflare JS challenges


class BrowserFetcher:
    """Lightweight wrapper around a Playwright Chromium instance.

    Handles browser lifecycle and provides a simple ``fetch(url) -> str | None``
    interface.  Instances are not thread-safe; create one per thread/process.
    """

    def __init__(self, headless: bool = True, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._browser = None
        self._playwright = None

    def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)

    def fetch(self, url: str, *, timeout_ms: int | None = None) -> str | None:
        """Open *url* in headless Chromium and return the final page HTML.

        Automatically waits for Cloudflare JavaScript challenges to resolve.
        Returns ``None`` on failure.
        """
        timeout = timeout_ms or self._timeout_ms
        try:
            self._ensure_browser()
            context = self._browser.new_context(user_agent=BROWSER_USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            # Give Cloudflare / turnstile challenges time to complete
            page.wait_for_timeout(CLOUDFLARE_WAIT_MS)
            html = page.content()
            context.close()
            return html
        except Exception:
            logger.debug("BrowserFetcher: failed to fetch %s", url, exc_info=True)
            return None

    def close(self):
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def browser_fetch(
    url: str,
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> str | None:
    """Convenience function: fetch *url* via headless Chromium.

    Opens and closes the browser on every call — suitable for occasional use.
    For bulk fetching, use ``BrowserFetcher`` as a context manager to reuse
    the browser process.
    """
    with BrowserFetcher(headless=headless, timeout_ms=timeout_ms) as fetcher:
        return fetcher.fetch(url, timeout_ms=timeout_ms)
