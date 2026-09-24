from django.test import TestCase

from knowledge.commands import (
    DeleteBlockCommand,
    DeletePageCommand,
    RestoreBlockCommand,
)
from knowledge.forms import DeleteBlockForm, DeletePageForm, RestoreBlockForm
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

    def test_rejects_restore_while_the_page_is_still_archived(self):
        # Otherwise the block would come back "active" but unreachable —
        # PageRepository excludes archived pages, so there'd be nowhere
        # to render it (see issue #122 follow-up).
        block = BlockFactory(user=self.user, page=self.page)
        page_form = DeletePageForm({"user": self.user.id, "page": self.page.uuid})
        self.assertTrue(page_form.is_valid(), page_form.errors)
        DeletePageCommand(page_form).execute()

        restore_form = RestoreBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertFalse(restore_form.is_valid())
        self.assertIn("block", restore_form.errors)

        block.refresh_from_db()
        self.assertFalse(block.is_active)

    def test_restoring_a_child_also_restores_its_inactive_ancestor_chain(self):
        # Deleting the root cascades to child/grandchild; restoring only
        # the grandchild (as a flat Trash-view row would let you do)
        # must not leave it orphaned under still-deleted ancestors.
        root = BlockFactory(user=self.user, page=self.page, content="root")
        child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="child"
        )
        grandchild = BlockFactory(
            user=self.user, page=self.page, parent=child, content="grandchild"
        )
        self._delete_block(root)

        form = RestoreBlockForm({"user": self.user.id, "block": grandchild.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestoreBlockCommand(form).execute()

        for b in (root, child, grandchild):
            b.refresh_from_db()
            self.assertTrue(b.is_active, f"{b.content} should be active")

        # Now reachable from the page tree, not just the flat queryset.
        roots = list(BlockRepository.get_root_blocks(self.page))
        self.assertEqual([b.content for b in roots], ["root"])
        self.assertEqual(
            [b.content for b in BlockRepository.get_child_blocks(root)], ["child"]
        )
        self.assertEqual(
            [b.content for b in BlockRepository.get_child_blocks(child)],
            ["grandchild"],
        )

    def test_restoring_ancestor_chain_does_not_touch_unrelated_siblings(self):
        root = BlockFactory(user=self.user, page=self.page, content="root")
        target_child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="target"
        )
        sibling = BlockFactory(
            user=self.user, page=self.page, parent=root, content="sibling"
        )
        self._delete_block(root)

        form = RestoreBlockForm({"user": self.user.id, "block": target_child.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        RestoreBlockCommand(form).execute()

        root.refresh_from_db()
        target_child.refresh_from_db()
        sibling.refresh_from_db()
        self.assertTrue(root.is_active)
        self.assertTrue(target_child.is_active)
        # The sibling was deleted in the same cascade but never asked
        # for — restoring the target's ancestor chain must not bring it
        # back too.
        self.assertFalse(sibling.is_active)
