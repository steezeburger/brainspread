from django.test import TestCase

from knowledge.commands import DeleteBlockCommand, RestoreBlockCommand
from knowledge.forms import DeleteBlockForm, RestoreBlockForm
from knowledge.repositories import BlockRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestRestoreBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _delete_block(self, block):
        form = DeleteBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

    def test_restores_the_block(self):
        block = BlockFactory(user=self.user, page=self.page)
        self._delete_block(block)

        form = RestoreBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestoreBlockCommand(form).execute()

        self.assertTrue(BlockRepository.get_queryset().filter(uuid=block.uuid).exists())
        block.refresh_from_db()
        self.assertTrue(block.is_active)
        self.assertIsNone(block.deleted_at)

    def test_restores_the_whole_subtree(self):
        root = BlockFactory(user=self.user, page=self.page, content="root")
        child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="child"
        )
        grandchild = BlockFactory(
            user=self.user, page=self.page, parent=child, content="grandchild"
        )
        self._delete_block(root)

        form = RestoreBlockForm({"user": self.user.id, "block": root.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestoreBlockCommand(form).execute()

        for b in (root, child, grandchild):
            b.refresh_from_db()
            self.assertTrue(b.is_active, f"{b.content} should be active")
            self.assertIsNone(b.deleted_at)

    def test_rejects_an_active_block(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = RestoreBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertFalse(form.is_valid())

    def test_rejects_another_users_deleted_block(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        block = BlockFactory(user=other, page=other_page)
        form = DeleteBlockForm({"user": other.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        DeleteBlockCommand(form).execute()

        restore_form = RestoreBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertFalse(restore_form.is_valid())
