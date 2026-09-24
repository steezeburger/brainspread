from django.test import TestCase

from knowledge.commands import DeleteBlockCommand, DeletePageCommand, ListTrashCommand
from knowledge.forms import DeleteBlockForm, DeletePageForm, ListTrashForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestListTrashCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _archive_page(self, page, user=None):
        form = DeletePageForm({"user": (user or self.user).id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageCommand(form).execute()

    def _delete_block(self, block):
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

    def test_lists_deleted_pages(self):
        active_page = PageFactory(user=self.user)
        deleted_page = PageFactory(user=self.user)
        self._archive_page(deleted_page)

        form = ListTrashForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTrashCommand(form).execute()

        uuids = [p["uuid"] for p in result["pages"]]
        self.assertIn(str(deleted_page.uuid), uuids)
        self.assertNotIn(str(active_page.uuid), uuids)

    def test_lists_deleted_blocks(self):
        page = PageFactory(user=self.user)
        active_block = BlockFactory(user=self.user, page=page)
        deleted_block = BlockFactory(user=self.user, page=page)
        self._delete_block(deleted_block)

        form = ListTrashForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTrashCommand(form).execute()

        uuids = [b["uuid"] for b in result["blocks"]]
        self.assertIn(str(deleted_block.uuid), uuids)
        self.assertNotIn(str(active_block.uuid), uuids)

    def test_blocks_dropped_by_a_page_archive_also_appear(self):
        # Trash lists deleted blocks alongside pages, including ones that
        # only became inactive because their page was archived.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        self._archive_page(page)

        form = ListTrashForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTrashCommand(form).execute()

        block_uuids = [b["uuid"] for b in result["blocks"]]
        self.assertIn(str(block.uuid), block_uuids)

    def test_scoped_to_the_requesting_user(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        self._archive_page(other_page, user=other)

        form = ListTrashForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTrashCommand(form).execute()

        self.assertEqual(result["pages"], [])
        self.assertEqual(result["blocks"], [])

    def test_ordered_most_recently_deleted_first(self):
        page_a = PageFactory(user=self.user)
        page_b = PageFactory(user=self.user)
        self._archive_page(page_a)
        self._archive_page(page_b)

        form = ListTrashForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTrashCommand(form).execute()

        uuids = [p["uuid"] for p in result["pages"]]
        self.assertEqual(uuids[:2], [str(page_b.uuid), str(page_a.uuid)])
