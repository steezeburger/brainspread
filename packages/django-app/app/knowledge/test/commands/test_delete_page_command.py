from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import DeletePageCommand
from knowledge.forms import DeletePageForm
from knowledge.repositories import BlockRepository, PageRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestDeletePageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_soft_deletes_page(self):
        page = PageFactory(user=self.user)
        form = DeletePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        DeletePageCommand(form).execute()

        self.assertFalse(PageRepository.get_queryset().filter(uuid=page.uuid).exists())
        page.refresh_from_db()
        self.assertFalse(page.is_active)
        self.assertIsNotNone(page.deleted_at)

    def test_cascades_to_every_block_on_the_page(self):
        page = PageFactory(user=self.user)
        root = BlockFactory(user=self.user, page=page, content="root")
        child = BlockFactory(user=self.user, page=page, parent=root, content="child")

        other_page = PageFactory(user=self.user)
        other_block = BlockFactory(user=self.user, page=other_page, content="other")

        form = DeletePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageCommand(form).execute()

        for b in (root, child):
            self.assertFalse(
                BlockRepository.get_queryset().filter(uuid=b.uuid).exists()
            )
            b.refresh_from_db()
            self.assertFalse(b.is_active)

        # A block on an unrelated page is untouched.
        self.assertTrue(
            BlockRepository.get_queryset().filter(uuid=other_block.uuid).exists()
        )

    def test_does_not_touch_already_deleted_blocks_deleted_at(self):
        # A block that was individually deleted before the page archive
        # keeps its own deleted_at timestamp rather than being re-stamped.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        block.delete()
        block.refresh_from_db()
        original_deleted_at = block.deleted_at

        form = DeletePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageCommand(form).execute()

        block.refresh_from_db()
        self.assertEqual(block.deleted_at, original_deleted_at)

    def test_rolls_back_block_cascade_if_the_page_delete_step_fails(self):
        # The block cascade and the page's own delete must commit or
        # fail together — otherwise a mid-cascade error leaves blocks
        # archived under a page that's still showing as active.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)

        form = DeletePageForm({"user": self.user.id, "page": page.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        with patch(
            "knowledge.models.page.Page.delete", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                DeletePageCommand(form).execute()

        page.refresh_from_db()
        block.refresh_from_db()
        self.assertTrue(page.is_active)
        self.assertTrue(block.is_active)
