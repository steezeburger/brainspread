from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .fetcher import DEFAULT_USER_AGENT

DEFAULT_TIMEOUT_MS = 20_000


@dataclass
class BrowserCapture:
    html: str
    final_url: str
    # Full-page PNG. Empty when the page (or browser) refused to render
    # one - callers treat that as best-effort and skip the screenshot.
    screenshot_bytes: bytes


def capture_with_browser(
    url: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    user_agent: Optional[str] = None,
) -> BrowserCapture:
    """
    Render `url` in headless Chromium and return the post-JS HTML plus a
    full-page screenshot. Used as a fallback when the plain httpx fetch
    produces near-empty content, i.e. a JS-rendered page - see
    CaptureWebArchiveCommand.

    Raises PlaywrightError (or lets network/OS errors propagate) on
    launch/navigation failure; the caller treats that as best-effort and
    keeps whatever the httpx-based fetch already produced.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(user_agent=user_agent or DEFAULT_USER_AGENT)
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                # Some pages never go network-idle (polling, analytics
                # beacons); the DOM is usually already settled well before
                # that, so keep going rather than treating this as fatal.
                pass

            html = page.content()
            final_url = page.url

            try:
                screenshot_bytes = page.screenshot(full_page=True, type="png")
            except PlaywrightError:
                screenshot_bytes = b""

            return BrowserCapture(
                html=html, final_url=final_url, screenshot_bytes=screenshot_bytes
            )
        finally:
            browser.close()
