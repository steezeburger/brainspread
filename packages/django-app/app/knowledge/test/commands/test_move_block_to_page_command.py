from django.test import TestCase

from knowledge.commands import MoveBlockToPageCommand
from knowledge.forms import MoveBlockToPageForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestMoveBlockToPageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_move_block_from_source_to_target_page(self):
        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        target_page = PageFactory(user=self.user, title="Inbox", slug="inbox")
        block = BlockFactory(user=self.user, page=source_page, content="idea", order=1)

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = MoveBlockToPageCommand(form).execute()

        self.assertTrue(result["moved"])
        self.assertEqual(result["target_page"]["slug"], "inbox")

        block.refresh_from_db()
        self.assertEqual(block.page_id, target_page.id)
        self.assertIsNone(block.parent)

    def test_should_place_moved_block_at_bottom_of_target(self):
        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        target_page = PageFactory(user=self.user, title="Inbox", slug="inbox")
        BlockFactory(user=self.user, page=target_page, content="existing 1", order=1)
        BlockFactory(user=self.user, page=target_page, content="existing 2", order=2)
        block = BlockFactory(user=self.user, page=source_page, content="moved", order=1)

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToPageCommand(form).execute()

        block.refresh_from_db()
        self.assertEqual(block.page_id, target_page.id)
        self.assertEqual(block.order, 3)

    def test_should_carry_descendants_along(self):
        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        target_page = PageFactory(user=self.user, title="Inbox", slug="inbox")
        parent = BlockFactory(
            user=self.user, page=source_page, content="parent", order=1
        )
        child = BlockFactory(
            user=self.user,
            page=source_page,
            parent=parent,
            content="child",
            order=2,
        )

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": parent.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToPageCommand(form).execute()

        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.page_id, target_page.id)
        self.assertEqual(child.page_id, target_page.id)
        # Hierarchy preserved — child still parented to parent on target.
        self.assertEqual(child.parent_id, parent.id)
        self.assertIsNone(parent.parent_id)

    def test_should_be_noop_when_block_already_root_on_target(self):
        target_page = PageFactory(user=self.user, title="Inbox", slug="inbox")
        block = BlockFactory(user=self.user, page=target_page, content="x", order=5)

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = MoveBlockToPageCommand(form).execute()
        self.assertFalse(result["moved"])

        block.refresh_from_db()
        self.assertEqual(block.order, 5)

    def test_should_reject_block_from_other_user(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user, title="theirs", slug="theirs")
        other_block = BlockFactory(user=other_user, page=other_page, content="x")
        target_page = PageFactory(user=self.user, title="Mine", slug="mine")

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": other_block.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertFalse(form.is_valid())

    def test_should_reject_target_page_from_other_user(self):
        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(user=self.user, page=source_page, content="x", order=1)
        other_user = UserFactory()
        other_page = PageFactory(user=other_user, title="theirs", slug="theirs")

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_page": other_page.uuid,
            }
        )
        self.assertFalse(form.is_valid())

    def test_should_promote_nested_block_to_root_on_target(self):
        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        target_page = PageFactory(user=self.user, title="Inbox", slug="inbox")
        parent = BlockFactory(
            user=self.user, page=source_page, content="parent", order=1
        )
        child = BlockFactory(
            user=self.user,
            page=source_page,
            parent=parent,
            content="moving child",
            order=2,
        )

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": child.uuid,
                "target_page": target_page.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToPageCommand(form).execute()

        child.refresh_from_db()
        parent.refresh_from_db()
        # child becomes root on target; parent stays on source.
        self.assertIsNone(child.parent_id)
        self.assertEqual(child.page_id, target_page.id)
        self.assertEqual(parent.page_id, source_page.id)


class TestMoveBlockToPageWithTargetParent(TestCase):
    """target_parent nests the moved subtree under an existing block
    (the "move under…" flow) instead of promoting it to page root."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.source_page = PageFactory(user=cls.user, title="Daily", slug="2026-01-01")
        cls.target_page = PageFactory(user=cls.user, title="Project", slug="project")
        cls.target_parent = BlockFactory(
            user=cls.user, page=cls.target_page, content="epic", order=1
        )

    def _move(self, block, **extra):
        form = MoveBlockToPageForm({"user": self.user, "block": block.uuid, **extra})
        self.assertTrue(form.is_valid(), form.errors)
        return MoveBlockToPageCommand(form).execute()

    def test_should_nest_block_under_target_parent(self):
        block = BlockFactory(
            user=self.user, page=self.source_page, content="todo", order=1
        )
        child = BlockFactory(
            user=self.user, page=self.source_page, parent=block, content="sub"
        )

        result = self._move(block, target_parent=self.target_parent.uuid)

        self.assertTrue(result["moved"])
        block.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(block.page_id, self.target_page.id)
        self.assertEqual(block.parent_id, self.target_parent.id)
        # Descendants follow to the target page but keep their nesting.
        self.assertEqual(child.page_id, self.target_page.id)
        self.assertEqual(child.parent_id, block.id)

    def test_should_derive_target_page_from_parent_when_omitted(self):
        block = BlockFactory(user=self.user, page=self.source_page, content="x")

        result = self._move(block, target_parent=self.target_parent.uuid)

        self.assertEqual(result["target_page"]["slug"], "project")

    def test_should_order_after_existing_children_of_parent(self):
        BlockFactory(
            user=self.user,
            page=self.target_page,
            parent=self.target_parent,
            content="existing child",
            order=5,
        )
        block = BlockFactory(user=self.user, page=self.source_page, content="x")

        self._move(block, target_parent=self.target_parent.uuid)

        block.refresh_from_db()
        self.assertEqual(block.parent_id, self.target_parent.id)
        self.assertEqual(block.order, 6)

    def test_should_renest_within_same_page(self):
        sibling = BlockFactory(
            user=self.user, page=self.target_page, content="stray", order=9
        )

        self._move(sibling, target_parent=self.target_parent.uuid)

        sibling.refresh_from_db()
        self.assertEqual(sibling.page_id, self.target_page.id)
        self.assertEqual(sibling.parent_id, self.target_parent.id)

    def test_should_reject_move_under_own_descendant(self):
        from django.core.exceptions import ValidationError

        block = BlockFactory(user=self.user, page=self.source_page, content="root")
        child = BlockFactory(
            user=self.user, page=self.source_page, parent=block, content="child"
        )

        with self.assertRaises(ValidationError):
            self._move(block, target_parent=child.uuid)

    def test_should_reject_mismatched_page_and_parent(self):
        other_page = PageFactory(user=self.user, title="Other", slug="other")
        block = BlockFactory(user=self.user, page=self.source_page, content="x")

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_page": other_page.uuid,
                "target_parent": self.target_parent.uuid,
            }
        )
        self.assertFalse(form.is_valid())

    def test_should_reject_target_parent_from_other_user(self):
        other_user = UserFactory()
        other_block = BlockFactory(user=other_user, content="theirs")
        block = BlockFactory(user=self.user, page=self.source_page, content="x")

        form = MoveBlockToPageForm(
            {
                "user": self.user,
                "block": block.uuid,
                "target_parent": other_block.uuid,
            }
        )
        self.assertFalse(form.is_valid())

    def test_should_be_noop_when_already_under_target_parent(self):
        block = BlockFactory(
            user=self.user,
            page=self.target_page,
            parent=self.target_parent,
            content="already here",
        )

        result = self._move(block, target_parent=self.target_parent.uuid)

        self.assertFalse(result["moved"])
