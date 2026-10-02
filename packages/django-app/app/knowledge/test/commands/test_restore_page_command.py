from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import DeletePageCommand, RestorePageCommand
from knowledge.forms import DeletePageForm, RestorePageForm
from knowledge.repositories import BlockRepository, PageRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestRestorePageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _archive_page(self, page):
        form = DeletePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageCommand(form).execute()

    def test_restores_the_page(self):
        page = PageFactory(user=self.user)
        self._archive_page(page)

        form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestorePageCommand(form).execute()

        self.assertTrue(PageRepository.get_queryset().filter(uuid=page.uuid).exists())
        page.refresh_from_db()
        self.assertTrue(page.is_active)
        self.assertIsNone(page.deleted_at)

    def test_restores_blocks_deleted_alongside_the_page(self):
        page = PageFactory(user=self.user)
        root = BlockFactory(user=self.user, page=page, content="root")
        child = BlockFactory(user=self.user, page=page, parent=root, content="child")
        self._archive_page(page)

        form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestorePageCommand(form).execute()

        for b in (root, child):
            self.assertTrue(BlockRepository.get_queryset().filter(uuid=b.uuid).exists())
            b.refresh_from_db()
            self.assertTrue(b.is_active)
            self.assertIsNone(b.deleted_at)

    def test_also_restores_a_block_deleted_independently_before_the_archive(self):
        # v1 keeps this simple: restoring a page brings back every block
        # that's currently inactive on it, whether it went inactive via
        # the page archive or was deleted on its own beforehand.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        block.delete()
        self._archive_page(page)

        form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestorePageCommand(form).execute()

        block.refresh_from_db()
        self.assertTrue(block.is_active)

    def test_rejects_an_active_page(self):
        page = PageFactory(user=self.user)
        form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertFalse(form.is_valid())

    def test_rejects_another_users_deleted_page(self):
        other = UserFactory()
        page = PageFactory(user=other)
        form = DeletePageForm({"user": other.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageCommand(form).execute()

        restore_form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertFalse(restore_form.is_valid())

    def test_rolls_back_page_undelete_if_the_block_restore_step_fails(self):
        # page.undelete() and the block cascade must commit or fail
        # together — otherwise a mid-cascade error leaves the page
        # active while its blocks are still archived (invisible and
        # stuck, with no Trash entry to recover from).
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        self._archive_page(page)

        form = RestorePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        with patch(
            "knowledge.repositories.block_repository.BlockRepository"
            ".restore_page_blocks",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                RestorePageCommand(form).execute()

        page.refresh_from_db()
        block.refresh_from_db()
        self.assertFalse(page.is_active)
        self.assertFalse(block.is_active)
