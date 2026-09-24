from django.test import TestCase

from knowledge.commands import DeleteBlockCommand
from knowledge.forms import DeleteBlockForm
from knowledge.models import Block
from knowledge.repositories import BlockRepository
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestDeleteBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_soft_deletes_block(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        DeleteBlockCommand(form).execute()

        # Row survives (recoverable), but drops out of the active queryset.
        self.assertFalse(
            BlockRepository.get_queryset().filter(uuid=block.uuid).exists()
        )
        block.refresh_from_db()
        self.assertFalse(block.is_active)
        self.assertIsNotNone(block.deleted_at)

    def test_cascades_to_descendant_subtree(self):
        root = BlockFactory(user=self.user, page=self.page, content="root")
        child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="child"
        )
        grandchild = BlockFactory(
            user=self.user, page=self.page, parent=child, content="grandchild"
        )
        # A sibling elsewhere in the tree must be untouched.
        sibling = BlockFactory(user=self.user, page=self.page, content="sibling")

        form = DeleteBlockForm({"user": self.user.id, "block": root.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

        for b in (root, child, grandchild):
            b.refresh_from_db()
            self.assertFalse(b.is_active, f"{b.content} should be inactive")
            self.assertIsNotNone(b.deleted_at)

        sibling.refresh_from_db()
        self.assertTrue(sibling.is_active)

    def test_soft_deletes_linked_web_archive_and_keeps_the_row(self):
        # When a block has an archive, deleting the block must not take
        # the archive with it - the captured bytes are durable data.
        block = BlockFactory(user=self.user, page=self.page)
        archive = WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/article",
            status="ready",
            title="Example",
        )

        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

        # Block row survives (soft-deleted); archive is soft-deleted too.
        block.refresh_from_db()
        self.assertFalse(block.is_active)
        archive.refresh_from_db()
        self.assertFalse(archive.is_active)
        self.assertIsNotNone(archive.deleted_at)
        # Metadata preserved so a future library/restore view can show it.
        self.assertEqual(archive.title, "Example")
        self.assertEqual(archive.source_url, "https://example.com/article")

    def test_soft_deletes_archives_for_the_whole_subtree(self):
        root = BlockFactory(user=self.user, page=self.page, content="root")
        child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="child"
        )
        root_archive = WebArchive.objects.create(
            user=self.user,
            block=root,
            source_url="https://example.com/root",
            status="ready",
        )
        child_archive = WebArchive.objects.create(
            user=self.user,
            block=child,
            source_url="https://example.com/child",
            status="ready",
        )

        form = DeleteBlockForm({"user": self.user.id, "block": root.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

        root_archive.refresh_from_db()
        child_archive.refresh_from_db()
        self.assertFalse(root_archive.is_active)
        self.assertFalse(child_archive.is_active)

    def test_is_a_noop_when_block_has_no_archive(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid())

        # Should not raise even though there's no archive for this block.
        DeleteBlockCommand(form).execute()

        block.refresh_from_db()
        self.assertFalse(block.is_active)
        self.assertEqual(WebArchive.objects.count(), 0)

    def test_still_exists_via_unfiltered_manager(self):
        # Sanity check that soft-delete never touches the raw row count —
        # only the active-only repository queryset excludes it.
        block = BlockFactory(user=self.user, page=self.page)
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid())

        DeleteBlockCommand(form).execute()

        self.assertTrue(Block.objects.filter(uuid=block.uuid).exists())
