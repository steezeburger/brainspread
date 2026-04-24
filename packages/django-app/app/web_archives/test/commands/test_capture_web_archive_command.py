from django.test import TestCase

from web_archives.commands import CaptureWebArchiveCommand
from web_archives.forms import CaptureWebArchiveForm
from web_archives.models import WebArchive
from web_archives.pipeline.fetcher import FetchedPage

from ..helpers import BlockFactory, PageFactory, UserFactory

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
      <p>First paragraph of the article.</p>
      <p>Second <strong>paragraph</strong> with emphasis.</p>
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
