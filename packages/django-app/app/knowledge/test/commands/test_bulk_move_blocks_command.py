from datetime import date

from django.test import TestCase

from knowledge.commands import BulkMoveBlocksCommand
from knowledge.forms import BulkMoveBlocksForm
from knowledge.models import Page

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestBulkMoveBlocksCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_move_blocks_to_target_daily_as_siblings(self):
        target_date = date(2026, 4, 29)
        source = PageFactory(user=self.user, title="Notes", slug="notes-move-1")
        b1 = BlockFactory(user=self.user, page=source, content="first", order=1)
        b2 = BlockFactory(user=self.user, page=source, content="second", order=2)

        form = BulkMoveBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(b1.uuid), str(b2.uuid)],
                "target_date": target_date,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksCommand(form).execute()

        self.assertEqual(result["moved_count"], 2)

        target_page = Page.objects.get(
            user=self.user, page_type="daily", date=target_date
        )
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.page, target_page)
        self.assertEqual(b2.page, target_page)
        self.assertIsNone(b1.parent)
        self.assertIsNone(b2.parent)

    def test_should_preserve_relative_order_on_target(self):
        # b1 and b2 are at orders 5 and 10 on the source. After move they
        # should land in that same relative order on the target page.
        target_date = date(2026, 4, 29)
        source = PageFactory(user=self.user, title="Notes", slug="notes-move-2")
        b1 = BlockFactory(user=self.user, page=source, content="first", order=5)
        b2 = BlockFactory(user=self.user, page=source, content="second", order=10)

        form = BulkMoveBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(b2.uuid), str(b1.uuid)],
                "target_date": target_date,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        BulkMoveBlocksCommand(form).execute()

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertLess(b1.order, b2.order)

    def test_should_preserve_parent_child_relationship_within_selection(self):
        target_date = date(2026, 4, 29)
        source = PageFactory(user=self.user, title="Notes", slug="notes-move-3")
        parent = BlockFactory(user=self.user, page=source, content="parent", order=1)
        child = BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            content="child",
            order=2,
        )

        form = BulkMoveBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(parent.uuid), str(child.uuid)],
                "target_date": target_date,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksCommand(form).execute()

        # Only the parent moves explicitly; child rides along.
        self.assertEqual(result["moved_count"], 1)

        parent.refresh_from_db()
        child.refresh_from_db()
        target_page = Page.objects.get(
            user=self.user, page_type="daily", date=target_date
        )
        self.assertEqual(parent.page, target_page)
        self.assertEqual(child.page, target_page)
        # Hierarchy preserved
        self.assertIsNone(parent.parent)
        self.assertEqual(child.parent, parent)

    def test_should_silently_skip_blocks_that_belong_to_another_user(self):
        target_date = date(2026, 4, 29)
        source = PageFactory(user=self.user, title="Notes", slug="notes-move-4")
        mine = BlockFactory(user=self.user, page=source, content="mine", order=1)

        other = UserFactory()
        other_page = PageFactory(user=other, slug="other-page-move")
        theirs = BlockFactory(user=other, page=other_page, content="theirs", order=1)

        form = BulkMoveBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(mine.uuid), str(theirs.uuid)],
                "target_date": target_date,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = BulkMoveBlocksCommand(form).execute()

        self.assertEqual(result["moved_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        # Other user's block stays put
        theirs.refresh_from_db()
        self.assertEqual(theirs.page, other_page)

    def test_should_create_daily_page_if_missing(self):
        target_date = date(2026, 4, 29)
        source = PageFactory(user=self.user, title="Notes", slug="notes-move-5")
        b = BlockFactory(user=self.user, page=source, content="x", order=1)

        self.assertFalse(
            Page.objects.filter(
                user=self.user, page_type="daily", date=target_date
            ).exists()
        )

        form = BulkMoveBlocksForm(
            {
                "user": self.user.id,
                "blocks": [str(b.uuid)],
                "target_date": target_date,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        BulkMoveBlocksCommand(form).execute()

        self.assertTrue(
            Page.objects.filter(
                user=self.user, page_type="daily", date=target_date
            ).exists()
        )

    def test_should_reject_empty_blocks_list(self):
        form = BulkMoveBlocksForm({"user": self.user.id, "blocks": []})
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)
