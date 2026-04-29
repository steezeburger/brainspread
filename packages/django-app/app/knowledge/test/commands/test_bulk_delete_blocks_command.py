from django.test import TestCase

from knowledge.commands import BulkDeleteBlocksCommand
from knowledge.forms import BulkDeleteBlocksForm
from knowledge.models import Block
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestBulkDeleteBlocksCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_should_delete_a_list_of_blocks(self):
        b1 = BlockFactory(user=self.user, page=self.page, content="a")
        b2 = BlockFactory(user=self.user, page=self.page, content="b")
        b3 = BlockFactory(user=self.user, page=self.page, content="c")

        form = BulkDeleteBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(b1.uuid), str(b2.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkDeleteBlocksCommand(form).execute()

        self.assertEqual(result["deleted_count"], 2)
        self.assertFalse(Block.objects.filter(uuid=b1.uuid).exists())
        self.assertFalse(Block.objects.filter(uuid=b2.uuid).exists())
        # Untouched
        self.assertTrue(Block.objects.filter(uuid=b3.uuid).exists())

    def test_should_skip_descendants_when_ancestor_is_also_in_selection(self):
        # Selecting both parent and child should result in a single delegated
        # delete (the parent) — the CASCADE on parent FK takes the child too.
        parent = BlockFactory(user=self.user, page=self.page, content="parent")
        child = BlockFactory(
            user=self.user, page=self.page, parent=parent, content="child"
        )

        form = BulkDeleteBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(parent.uuid), str(child.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkDeleteBlocksCommand(form).execute()

        # Only the parent root was explicitly deleted; child cascaded.
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(Block.objects.filter(uuid=parent.uuid).exists())
        self.assertFalse(Block.objects.filter(uuid=child.uuid).exists())

    def test_should_soft_delete_attached_web_archives(self):
        # Bulk delete must use the same archive-cascade path as the per-block
        # command so durable bytes survive.
        block = BlockFactory(user=self.user, page=self.page)
        archive = WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/x",
            status="ready",
            title="Example",
        )

        form = BulkDeleteBlocksForm({"user": self.user.id, "blocks": [str(block.uuid)]})
        self.assertTrue(form.is_valid(), form.errors)

        BulkDeleteBlocksCommand(form).execute()

        archive.refresh_from_db()
        self.assertFalse(archive.is_active)
        self.assertIsNone(archive.block_id)
        self.assertEqual(archive.title, "Example")

    def test_should_silently_skip_blocks_that_belong_to_another_user(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        mine = BlockFactory(user=self.user, page=self.page, content="mine")
        theirs = BlockFactory(user=other, page=other_page, content="theirs")

        form = BulkDeleteBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(mine.uuid), str(theirs.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkDeleteBlocksCommand(form).execute()

        # Only mine was eligible
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertFalse(Block.objects.filter(uuid=mine.uuid).exists())
        self.assertTrue(Block.objects.filter(uuid=theirs.uuid).exists())

    def test_should_reject_an_empty_blocks_list(self):
        form = BulkDeleteBlocksForm({"user": self.user.id, "blocks": []})
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_should_reject_invalid_uuids(self):
        form = BulkDeleteBlocksForm({"user": self.user.id, "blocks": ["not-a-uuid"]})
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)
