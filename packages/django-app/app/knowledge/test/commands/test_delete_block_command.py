from django.test import TestCase

from knowledge.commands import DeleteBlockCommand
from knowledge.forms import DeleteBlockForm
from knowledge.models import Block
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestDeleteBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_deletes_block(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        DeleteBlockCommand(form).execute()

        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())

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

        # Block is gone, archive row is still there but soft-deleted and
        # unhooked from the (now-deleted) block.
        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())
        archive.refresh_from_db()
        self.assertFalse(archive.is_active)
        self.assertIsNotNone(archive.deleted_at)
        self.assertIsNone(archive.block_id)
        # Metadata preserved so a future library/restore view can show it.
        self.assertEqual(archive.title, "Example")
        self.assertEqual(archive.source_url, "https://example.com/article")

    def test_is_a_noop_when_block_has_no_archive(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid())

        # Should not raise even though there's no archive for this block.
        DeleteBlockCommand(form).execute()

        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())
        self.assertEqual(WebArchive.objects.count(), 0)
