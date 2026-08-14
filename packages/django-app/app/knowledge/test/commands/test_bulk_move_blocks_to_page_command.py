from django.test import TestCase

from knowledge.commands import BulkMoveBlocksToPageCommand
from knowledge.forms import BulkMoveBlocksToPageForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestBulkMoveBlocksToPageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _form(self, *, blocks, target_page):
        return BulkMoveBlocksToPageForm(
            {
                "user": self.user.id,
                "blocks": blocks,
                "target_page": str(target_page.uuid),
            }
        )

    def test_should_move_blocks_to_target_page_as_siblings(self):
        source = PageFactory(user=self.user, title="Notes", slug="notes-mp-1")
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-1")
        b1 = BlockFactory(user=self.user, page=source, content="first", order=1)
        b2 = BlockFactory(user=self.user, page=source, content="second", order=2)

        form = self._form(blocks=[str(b1.uuid), str(b2.uuid)], target_page=target)
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksToPageCommand(form).execute()

        self.assertEqual(result["moved_count"], 2)
        self.assertEqual(result["target_page"]["uuid"], str(target.uuid))

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.page, target)
        self.assertEqual(b2.page, target)
        self.assertIsNone(b1.parent)
        self.assertIsNone(b2.parent)

    def test_should_preserve_relative_order_on_target(self):
        source = PageFactory(user=self.user, title="Notes", slug="notes-mp-2")
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-2")
        b1 = BlockFactory(user=self.user, page=source, content="first", order=5)
        b2 = BlockFactory(user=self.user, page=source, content="second", order=10)

        form = self._form(blocks=[str(b2.uuid), str(b1.uuid)], target_page=target)
        self.assertTrue(form.is_valid(), form.errors)

        BulkMoveBlocksToPageCommand(form).execute()

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertLess(b1.order, b2.order)

    def test_should_preserve_parent_child_relationship_within_selection(self):
        source = PageFactory(user=self.user, title="Notes", slug="notes-mp-3")
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-3")
        parent = BlockFactory(user=self.user, page=source, content="parent", order=1)
        child = BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            content="child",
            order=2,
        )

        form = self._form(
            blocks=[str(parent.uuid), str(child.uuid)], target_page=target
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksToPageCommand(form).execute()

        # Only the parent moves explicitly; child rides along via the
        # MoveBlockToPageCommand's descendants pass.
        self.assertEqual(result["moved_count"], 1)

        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.page, target)
        self.assertEqual(child.page, target)
        self.assertIsNone(parent.parent)
        self.assertEqual(child.parent, parent)

    def test_should_silently_skip_blocks_owned_by_another_user(self):
        # Cross-user uuids are filtered out by the user-scoped queryset
        # in execute(); they show up only in skipped_count and don't
        # touch the other user's data.
        source = PageFactory(user=self.user, title="Notes", slug="notes-mp-4")
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-4")
        mine = BlockFactory(user=self.user, page=source, content="mine", order=1)

        other = UserFactory()
        other_page = PageFactory(user=other, slug="other-page-mp")
        theirs = BlockFactory(user=other, page=other_page, content="theirs", order=1)

        form = self._form(blocks=[str(mine.uuid), str(theirs.uuid)], target_page=target)
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksToPageCommand(form).execute()

        self.assertEqual(result["moved_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        theirs.refresh_from_db()
        self.assertEqual(theirs.page, other_page)

    def test_should_reject_target_page_owned_by_another_user(self):
        # The form's clean_target_page guard rejects cross-user target
        # pages so a hostile request can't write into someone else's
        # page.
        source = PageFactory(user=self.user, title="Notes", slug="notes-mp-5")
        b = BlockFactory(user=self.user, page=source, content="x", order=1)

        other = UserFactory()
        other_target = PageFactory(user=other, slug="other-target-mp")

        form = self._form(blocks=[str(b.uuid)], target_page=other_target)
        self.assertFalse(form.is_valid())
        self.assertIn("target_page", form.errors)

    def test_should_reject_empty_blocks_list(self):
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-6")
        form = self._form(blocks=[], target_page=target)
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_should_no_op_when_blocks_already_on_target(self):
        # MoveBlockToPageCommand returns moved=False for blocks already
        # root on the target. moved_count reflects only real movements
        # so the toast can stay accurate.
        target = PageFactory(user=self.user, title="Backlog", slug="backlog-mp-7")
        already = BlockFactory(user=self.user, page=target, content="x", order=1)

        form = self._form(blocks=[str(already.uuid)], target_page=target)
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksToPageCommand(form).execute()
        self.assertEqual(result["moved_count"], 0)
        self.assertEqual(result["skipped_count"], 0)


class TestBulkMoveBlocksToPageWithTargetParent(TestCase):
    """Bulk "move under…": every selected top block nests under the
    target parent; intra-selection hierarchy is preserved."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.source_page = PageFactory(user=cls.user, title="Daily", slug="2026-01-02")
        cls.target_page = PageFactory(user=cls.user, title="Project", slug="project-b")
        cls.target_parent = BlockFactory(
            user=cls.user, page=cls.target_page, content="epic", order=1
        )

    def _bulk_move(self, blocks, **extra):
        form = BulkMoveBlocksToPageForm(
            {
                "user": self.user,
                "blocks": [str(b.uuid) for b in blocks],
                **extra,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return BulkMoveBlocksToPageCommand(form).execute()

    def test_should_nest_selection_under_target_parent(self):
        a = BlockFactory(user=self.user, page=self.source_page, content="a", order=1)
        a_child = BlockFactory(
            user=self.user, page=self.source_page, parent=a, content="a1"
        )
        b = BlockFactory(user=self.user, page=self.source_page, content="b", order=2)

        result = self._bulk_move([a, a_child, b], target_parent=self.target_parent.uuid)

        self.assertEqual(result["moved_count"], 2)  # a + b; a1 rides along
        for blk in (a, a_child, b):
            blk.refresh_from_db()
        self.assertEqual(a.parent_id, self.target_parent.id)
        self.assertEqual(b.parent_id, self.target_parent.id)
        self.assertEqual(a_child.parent_id, a.id)
        self.assertEqual(a_child.page_id, self.target_page.id)
        # Relative order preserved under the new parent.
        self.assertLess(a.order, b.order)

    def test_should_skip_block_containing_target_parent(self):
        # Selecting an ancestor of the target parent must not nuke the
        # tree — that block is skipped, others still move.
        container = BlockFactory(
            user=self.user, page=self.target_page, content="container", order=2
        )
        nested_parent = BlockFactory(
            user=self.user, page=self.target_page, parent=container, content="nest"
        )
        mover = BlockFactory(
            user=self.user, page=self.source_page, content="mover", order=1
        )

        result = self._bulk_move([container, mover], target_parent=nested_parent.uuid)

        self.assertEqual(result["moved_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        container.refresh_from_db()
        mover.refresh_from_db()
        self.assertIsNone(container.parent_id)
        self.assertEqual(mover.parent_id, nested_parent.id)
