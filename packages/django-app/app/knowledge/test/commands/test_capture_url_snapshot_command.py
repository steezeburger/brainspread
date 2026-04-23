from django.test import TestCase

from knowledge.commands import CaptureUrlSnapshotCommand
from knowledge.forms import CaptureUrlSnapshotForm
from knowledge.models import Snapshot
from knowledge.snapshots.fetcher import FetchedPage

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


def make_fake_fetcher(html: str = SAMPLE_HTML, final_url: str = None):
    def fake_fetch(url: str, **_):
        return FetchedPage(
            url=url,
            final_url=final_url or url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            html=html,
        )

    return fake_fetch


class TestCaptureUrlSnapshotCommand(TestCase):
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
        return CaptureUrlSnapshotForm(data)

    def test_should_create_pending_snapshot_and_mark_block_embed(self):
        block = BlockFactory(user=self.user, page=self.page, content="")
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid(), form.errors)

        # run_async=False so we capture synchronously in tests, and inject
        # a fake fetcher so we don't hit the network.
        command = CaptureUrlSnapshotCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        )
        snapshot = command.execute()

        block.refresh_from_db()
        self.assertEqual(block.content_type, "embed")
        self.assertEqual(block.media_url, "https://example.com/article")

        self.assertEqual(snapshot.status, "ready")
        self.assertEqual(snapshot.source_url, "https://example.com/article")
        # og:title wins over <title> when present
        self.assertEqual(snapshot.title, "Example Article - OG")
        self.assertEqual(snapshot.site_name, "Example Blog")
        self.assertEqual(snapshot.author, "Jane Doe")
        self.assertEqual(snapshot.canonical_url, "https://example.com/article")
        self.assertTrue(snapshot.favicon_url.endswith("/favicon.ico"))
        self.assertEqual(snapshot.og_image_url, "https://example.com/images/hero.png")
        self.assertIsNotNone(snapshot.published_at)
        self.assertTrue(snapshot.excerpt)
        self.assertTrue(snapshot.word_count and snapshot.word_count > 0)
        self.assertIn("First paragraph", snapshot.extracted_text)
        self.assertNotIn("skip me", snapshot.extracted_text)
        self.assertNotIn("alert", snapshot.extracted_text)
        self.assertTrue(snapshot.readable_asset_id)
        self.assertTrue(snapshot.raw_asset_id)
        self.assertEqual(len(snapshot.text_sha256), 64)

    def test_should_mark_snapshot_failed_on_fetch_error(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        def broken_fetcher(url: str, **_):
            raise RuntimeError("boom")

        command = CaptureUrlSnapshotCommand(
            form, run_async=False, fetcher=broken_fetcher
        )
        snapshot = command.execute()

        self.assertEqual(snapshot.status, "failed")
        self.assertIn("boom", snapshot.failure_reason)
        self.assertFalse(snapshot.readable_asset_id)

    def test_should_update_existing_snapshot_when_recapturing(self):
        block = BlockFactory(user=self.user, page=self.page)
        Snapshot.objects.create(
            user=self.user,
            block=block,
            source_url="https://old.example.com",
            status="failed",
            failure_reason="prior run",
        )

        form = self._make_form(block_uuid=block.uuid, url="https://example.com/article")
        self.assertTrue(form.is_valid())

        CaptureUrlSnapshotCommand(
            form, run_async=False, fetcher=make_fake_fetcher()
        ).execute()

        # Still one snapshot per block - old row got updated in place.
        self.assertEqual(Snapshot.objects.filter(block=block).count(), 1)
        snapshot = Snapshot.objects.get(block=block)
        self.assertEqual(snapshot.status, "ready")
        self.assertEqual(snapshot.source_url, "https://example.com/article")
        self.assertEqual(snapshot.failure_reason, "")

    def test_should_update_block_content_to_extracted_title(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="https://example.com/article"
        )
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        CaptureUrlSnapshotCommand(
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

    def test_returns_pending_snapshot_immediately_when_async(self):
        # Verifies run_async=True path creates a pending row synchronously
        # and returns before capture completes. We don't join the thread
        # because DB state across threads is not guaranteed inside the
        # test transaction.
        block = BlockFactory(user=self.user, page=self.page)
        form = self._make_form(block_uuid=block.uuid)
        self.assertTrue(form.is_valid())

        command = CaptureUrlSnapshotCommand(
            form, run_async=True, fetcher=make_fake_fetcher()
        )
        snapshot = command.execute()

        self.assertEqual(snapshot.source_url, "https://example.com/article")
        self.assertEqual(snapshot.status, "pending")
