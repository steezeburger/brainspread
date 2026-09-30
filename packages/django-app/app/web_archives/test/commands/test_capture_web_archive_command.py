from django.test import TestCase

from web_archives.commands import CaptureWebArchiveCommand
from web_archives.forms import CaptureWebArchiveForm
from web_archives.models import WebArchive
from web_archives.pipeline import BrowserCapture
from web_archives.pipeline.fetcher import FetchedPage

from ..helpers import BlockFactory, PageFactory, UserFactory

# A JS-rendered-shell page: no textual content until client-side JS runs,
# so the httpx-based fetch + extractor sees ~0 chars of body text.
JS_SHELL_HTML = """
<!doctype html>
<html>
  <head><title>App Shell</title></head>
  <body><div id="root"></div><script src="/app.js"></script></body>
</html>
"""

# Stand-in for what Playwright would hand back after running that page's JS.
RENDERED_HTML = """
<!doctype html>
<html>
  <head>
    <title>Rendered Article</title>
    <meta property="og:title" content="Rendered Article" />
  </head>
  <body>
    <article>
      <h1>Rendered Article</h1>
      <p>This paragraph only exists after JavaScript executes and renders
      real content into the page body for the reader.</p>
      <p>A second paragraph with plenty of words so the extracted text
      clears the near-empty threshold comfortably on the rendered pass.</p>
    </article>
  </body>
</html>
"""


def make_fake_browser_fetcher(
    html: str = RENDERED_HTML,
    final_url: str = None,
    screenshot_bytes: bytes = b"fake-png-bytes",
):
    calls = []

    def fake_capture(url: str, **_):
        calls.append(url)
        return BrowserCapture(
            html=html, final_url=final_url or url, screenshot_bytes=screenshot_bytes
        )

    fake_capture.calls = calls
    return fake_capture


def make_broken_browser_fetcher(message: str = "browser boom"):
    def fake_capture(url: str, **_):
        raise RuntimeError(message)

    return fake_capture


SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>Example Article</title>
    <meta property="og:title" content="Example Article - OG" />
    <meta property="og:site_name" content="Example Blog" />
    <meta name="author" content="Jane Doe" />
    <meta name="description" content="A short description of the article." />
    <meta property="article:published_time" content="2025-01-15T10:00:00+00:00" />
    <meta property="og:image" content="/images/hero.png" />
    <link rel="canonical" href="https://example.com/article" />
    <link rel="icon" href="/favicon.ico" />
  </head>
  <body>
    <nav>skip me</nav>
    <article>
      <h1>Example Article</h1>
      <p>First paragraph of the article, with enough real sentence content
      that the readability-based extractor has something substantial to
      score and select as the main body candidate.</p>
      <p>Second <strong>paragraph</strong> with emphasis, continuing the
      article for a few more sentences so the extracted plain text clears
      comfortably past the near-empty threshold used for the browser
      fallback decision.</p>
      <script>alert('skip')</script>
    </article>
    <footer>skip me too</footer>
  </body>
</html>
"""


def make_fake_fetcher(
    html: str = SAMPLE_HTML,
    final_url: str = None,
    content_type: str = "text/html; charset=utf-8",
    content_bytes: bytes = None,
):
    def fake_fetch(url: str, **_):
        body = content_bytes if content_bytes is not None else html.encode("utf-8")
        return FetchedPage(
            url=url,
            final_url=final_url or url,
            status_code=200,
            content_type=content_type,
            content_bytes=body,
            html=html if "text/html" in content_type else "",
        )

    return fake_fetch


class TestCaptureWebArchiveCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _make_form(self, **overrides):
        data = {
            "user": self.user.id,
            "block": overrides.pop("block_uuid", None),
            "url": overrides.pop("url", "https://example.com/article"),
        }
        data.update(overrides)
        return CaptureWebArchiveForm(data)

    def test_should_create_pending_archive_and_mark_block_embed(self):
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid(), form.errors)

        # run_async=False so we capture synchronously in tests, and inject
        # a fake fetcher so we don't hit the network.
        command = CaptureWebArchiveCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        )
        archive = command.execute()

        block.refresh_from_db()
        self.assertEqual(block.content_type, "embed")
        self.assertEqual(block.media_url, "https://example.com/article")

        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.source_url, "https://example.com/article")
        # og:title wins over <title> when present
        self.assertEqual(archive.title, "Example Article - OG")
        self.assertEqual(archive.site_name, "Example Blog")
        self.assertEqual(archive.author, "Jane Doe")
        self.assertEqual(archive.canonical_url, "https://example.com/article")
        self.assertTrue(archive.favicon_url.endswith("/favicon.ico"))
        self.assertEqual(archive.og_image_url, "https://example.com/images/hero.png")
        self.assertIsNotNone(archive.published_at)
        self.assertTrue(archive.excerpt)
        self.assertTrue(archive.word_count and archive.word_count > 0)
        self.assertIn("First paragraph", archive.extracted_text)
        self.assertNotIn("skip me", archive.extracted_text)
        self.assertNotIn("alert", archive.extracted_text)
        self.assertTrue(archive.readable_asset_id)
        self.assertTrue(archive.raw_asset_id)
        self.assertEqual(len(archive.text_sha256), 64)

    def test_should_mark_archive_failed_on_fetch_error(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        def broken_fetcher(url: str, **_):
            raise RuntimeError("boom")

        command = CaptureWebArchiveCommand(
            form, run_async=False, fetcher=broken_fetcher
        )
        archive = command.execute()

        self.assertEqual(archive.status, "failed")
        self.assertIn("boom", archive.failure_reason)
        self.assertFalse(archive.readable_asset_id)

    def test_should_update_existing_archive_when_recapturing(self):
        block = BlockFactory(user=self.user, page=self.page)
        WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://old.example.com",
            status="failed",
            failure_reason="prior run",
        )

        form = self._make_form(block_uuid=block.uuid, url="https://example.com/article")
        self.assertTrue(form.is_valid())

        CaptureWebArchiveCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        ).execute()

        # Still one archive per block - old row got updated in place.
        self.assertEqual(WebArchive.objects.filter(block=block).count(), 1)
        archive = WebArchive.objects.get(block=block)
        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.source_url, "https://example.com/article")
        self.assertEqual(archive.failure_reason, "")

    def test_should_update_block_content_to_extracted_title(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="https://example.com/article"
        )
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        CaptureWebArchiveCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        ).execute()

        block.refresh_from_db()
        self.assertEqual(block.content, "Example Article - OG")

    def test_should_preserve_trailing_tags_when_overwriting_title(self):
        # User can tag an embed via the chip UI before capture finishes;
        # those trailing hashtags must survive the title overwrite so we
        # don't silently drop their work.
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="https://example.com/article #news #ai-research",
        )
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        CaptureWebArchiveCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        ).execute()

        block.refresh_from_db()
        self.assertEqual(block.content, "Example Article - OG #news #ai-research")

    def test_should_reject_block_owned_by_other_user(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user)
        stranger_block = BlockFactory(user=other_user, page=other_page)

        form = self._make_form(block_uuid=stranger_block.uuid)
        self.assertFalse(form.is_valid())
        self.assertIn("block", form.errors)

    def test_returns_pending_archive_immediately_when_async(self):
        # Verifies run_async=True path creates a pending row synchronously
        # and returns before capture completes. We don't join the thread
        # because DB state across threads is not guaranteed inside the
        # test transaction.
        block = BlockFactory(user=self.user, page=self.page)
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        command = CaptureWebArchiveCommand(
            form, run_async=True, fetcher=make_fake_fetcher()
        )
        archive = command.execute()

        self.assertEqual(archive.source_url, "https://example.com/article")
        self.assertEqual(archive.status, "pending")

    def test_should_store_pdf_bytes_verbatim_for_non_html_content(self):
        # PDFs and other binary payloads bypass the HTML extractor. The
        # bytes land in an Asset with the correct mime type so the
        # "open archive" UI can actually render them.
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(
            block_uuid=block.uuid,
            url="https://example.com/papers/liquidtext.pdf",
        )
        self.assertTrue(form.is_valid(), form.errors)

        pdf_bytes = b"%PDF-1.4 stub body"
        fetcher = make_fake_fetcher(
            content_type="application/pdf",
            content_bytes=pdf_bytes,
            html="",
        )

        command = CaptureWebArchiveCommand(form, run_async=False, fetcher=fetcher)
        archive = command.execute()

        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.title, "liquidtext.pdf")
        self.assertTrue(archive.readable_asset_id)
        # Readable and raw should point at the same blob so the reader
        # endpoint has something to serve.
        self.assertEqual(archive.readable_asset_id, archive.raw_asset_id)
        self.assertEqual(archive.readable_asset.mime_type, "application/pdf")
        with archive.readable_asset.file.open("rb") as fh:
            self.assertEqual(fh.read(), pdf_bytes)

        block.refresh_from_db()
        self.assertEqual(block.content, "liquidtext.pdf")

    def test_should_fall_back_to_browser_when_extraction_is_near_empty(self):
        # httpx fetch of a JS-rendered shell page yields ~0 chars of text;
        # the command should retry via the (fake) browser fetcher and use
        # its richer result, including the screenshot it captured.
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid, url="https://example.com/spa")
        self.assertTrue(form.is_valid(), form.errors)

        browser_fetcher = make_fake_browser_fetcher()
        command = CaptureWebArchiveCommand(
            form,
            run_async=False,
            fetcher=make_fake_fetcher(html=JS_SHELL_HTML),
            browser_fetcher=browser_fetcher,
        )
        archive = command.execute()

        self.assertEqual(browser_fetcher.calls, ["https://example.com/spa"])
        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.title, "Rendered Article")
        self.assertIn("second paragraph", archive.extracted_text)
        self.assertTrue(archive.screenshot_asset_id)
        with archive.screenshot_asset.file.open("rb") as fh:
            self.assertEqual(fh.read(), b"fake-png-bytes")
        self.assertEqual(archive.screenshot_asset.mime_type, "image/png")

    def test_should_not_invoke_browser_fallback_when_extraction_has_enough_text(self):
        # The common case (server-rendered HTML, plenty of extracted text)
        # should never pay for a browser launch.
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid(), form.errors)

        browser_fetcher = make_fake_browser_fetcher()
        command = CaptureWebArchiveCommand(
            form,
            run_async=False,
            fetcher=make_fake_fetcher(),
            browser_fetcher=browser_fetcher,
        )
        archive = command.execute()

        self.assertEqual(browser_fetcher.calls, [])
        self.assertEqual(archive.status, "ready")
        self.assertFalse(archive.screenshot_asset_id)

    def test_should_keep_near_empty_result_when_browser_fallback_fails(self):
        # Browser launch/navigation errors are best-effort - the capture
        # should still complete "ready" with whatever the httpx fetch
        # produced, rather than failing the whole archive.
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid, url="https://example.com/spa")
        self.assertTrue(form.is_valid(), form.errors)

        command = CaptureWebArchiveCommand(
            form,
            run_async=False,
            fetcher=make_fake_fetcher(html=JS_SHELL_HTML),
            browser_fetcher=make_broken_browser_fetcher(),
        )
        archive = command.execute()

        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.extracted_text, "")
        self.assertFalse(archive.screenshot_asset_id)

    def test_should_capture_screenshot_even_when_rendered_text_is_not_better(self):
        # A screenshot is worth keeping any time the browser fallback ran
        # successfully, even if the rendered page didn't yield more text
        # than the original (still-near-empty) extraction did.
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid, url="https://example.com/spa")
        self.assertTrue(form.is_valid(), form.errors)

        browser_fetcher = make_fake_browser_fetcher(html=JS_SHELL_HTML)
        command = CaptureWebArchiveCommand(
            form,
            run_async=False,
            fetcher=make_fake_fetcher(html=JS_SHELL_HTML),
            browser_fetcher=browser_fetcher,
        )
        archive = command.execute()

        self.assertEqual(archive.status, "ready")
        self.assertEqual(archive.extracted_text, "")
        self.assertTrue(archive.screenshot_asset_id)
