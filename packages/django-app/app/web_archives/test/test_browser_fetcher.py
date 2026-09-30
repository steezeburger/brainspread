import os
import tempfile

import pytest
from django.test import SimpleTestCase

from web_archives.pipeline.browser_fetcher import capture_with_browser

# Launches a real headless Chromium via Playwright, so it needs the
# browser installed (see the Dockerfile's `playwright install` step) -
# marked integration so it can be deselected with -m "not integration"
# in environments without one. Uses a file:// URL so it doesn't need
# outbound network access.
pytestmark = pytest.mark.integration


class TestBrowserFetcher(SimpleTestCase):
    def test_renders_page_and_captures_screenshot(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as fh:
            fh.write(
                """
                <html><body>
                  <div id="root">loading...</div>
                  <script>
                    document.getElementById("root").textContent = "Rendered by JS";
                  </script>
                </body></html>
                """
            )
            path = fh.name

        try:
            result = capture_with_browser(f"file://{path}")
        finally:
            os.remove(path)

        self.assertIn("Rendered by JS", result.html)
        self.assertTrue(result.screenshot_bytes)
        self.assertTrue(result.screenshot_bytes.startswith(b"\x89PNG"))
