from datetime import date
from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import MoveBlockToDailyCommand
from knowledge.forms import MoveBlockToDailyForm
from knowledge.models import Block, Page

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestMoveBlockToDailyCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_move_block_from_other_page_to_today(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(
            user=self.user,
            page=source_page,
            content="some idea",
            block_type="bullet",
            order=1,
        )

        form = MoveBlockToDailyForm({"user": self.user, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        result = MoveBlockToDailyCommand(form).execute()

        self.assertTrue(result["moved"])
        self.assertEqual(result["target_page"]["date"], today.isoformat())

        block.refresh_from_db()
        self.assertEqual(block.page.date, today)
        self.assertEqual(block.page.page_type, "daily")
        self.assertIsNone(block.parent)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_place_block_at_bottom_of_target_page(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        today_page = PageFactory(
            user=self.user,
            date=today,
            page_type="daily",
            title="2026-04-29",
            slug="2026-04-29",
        )
        BlockFactory(user=self.user, page=today_page, content="existing 1", order=1)
        BlockFactory(user=self.user, page=today_page, content="existing 2", order=2)

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(
            user=self.user, page=source_page, content="moved", order=1
        )

        form = MoveBlockToDailyForm({"user": self.user, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToDailyCommand(form).execute()

        block.refresh_from_db()
        self.assertEqual(block.page, today_page)
        self.assertEqual(block.order, 3)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_move_descendants_with_block(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        parent = BlockFactory(
            user=self.user, page=source_page, content="parent", order=1
        )
        child = BlockFactory(
            user=self.user, page=source_page, parent=parent, content="child", order=2
        )
        grandchild = BlockFactory(
            user=self.user,
            page=source_page,
            parent=child,
            content="grandchild",
            order=3,
        )

        form = MoveBlockToDailyForm({"user": self.user, "block": parent.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToDailyCommand(form).execute()

        parent.refresh_from_db()
        child.refresh_from_db()
        grandchild.refresh_from_db()

        target_page = Page.objects.get(user=self.user, date=today, page_type="daily")
        self.assertEqual(parent.page, target_page)
        self.assertEqual(child.page, target_page)
        self.assertEqual(grandchild.page, target_page)

        # Hierarchy preserved
        self.assertIsNone(parent.parent)
        self.assertEqual(child.parent, parent)
        self.assertEqual(grandchild.parent, child)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_promote_nested_block_to_root_on_target(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
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

        form = MoveBlockToDailyForm({"user": self.user, "block": child.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToDailyCommand(form).execute()

        child.refresh_from_db()
        parent.refresh_from_db()

        # child becomes root on the daily page; parent stays put
        self.assertIsNone(child.parent)
        self.assertEqual(child.page.date, today)
        self.assertEqual(parent.page, source_page)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_create_daily_page_if_missing(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(user=self.user, page=source_page, content="x", order=1)

        self.assertFalse(
            Page.objects.filter(
                user=self.user, page_type="daily", date=today
            ).exists()
        )

        form = MoveBlockToDailyForm({"user": self.user, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToDailyCommand(form).execute()

        self.assertTrue(
            Page.objects.filter(
                user=self.user, page_type="daily", date=today
            ).exists()
        )

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_be_noop_when_block_already_root_on_target(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        today_page = PageFactory(
            user=self.user,
            date=today,
            page_type="daily",
            title="2026-04-29",
            slug="2026-04-29",
        )
        block = BlockFactory(user=self.user, page=today_page, content="x", order=5)

        form = MoveBlockToDailyForm({"user": self.user, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        result = MoveBlockToDailyCommand(form).execute()

        self.assertFalse(result["moved"])
        block.refresh_from_db()
        self.assertEqual(block.order, 5)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_use_target_date_when_provided(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today
        target_date = date(2026, 5, 1)

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(user=self.user, page=source_page, content="x", order=1)

        form = MoveBlockToDailyForm(
            {"user": self.user, "block": block.uuid, "target_date": target_date}
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = MoveBlockToDailyCommand(form).execute()

        self.assertTrue(result["moved"])
        self.assertEqual(result["target_page"]["date"], target_date.isoformat())

        block.refresh_from_db()
        self.assertEqual(block.page.date, target_date)

    def test_should_reject_block_belonging_to_another_user(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user, title="Other", slug="other")
        other_block = BlockFactory(user=other_user, page=other_page, content="x")

        form = MoveBlockToDailyForm(
            {"user": self.user, "block": other_block.uuid}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("block", form.errors)

    @patch("knowledge.commands.move_block_to_daily_command.date")
    def test_should_not_disrupt_unrelated_blocks_on_target_page(self, mock_date):
        today = date(2026, 4, 29)
        mock_date.today.return_value = today

        today_page = PageFactory(
            user=self.user,
            date=today,
            page_type="daily",
            title="2026-04-29",
            slug="2026-04-29",
        )
        existing_parent = BlockFactory(
            user=self.user, page=today_page, content="existing parent", order=1
        )
        existing_child = BlockFactory(
            user=self.user,
            page=today_page,
            parent=existing_parent,
            content="existing child",
            order=2,
        )

        source_page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(
            user=self.user, page=source_page, content="moved", order=1
        )

        form = MoveBlockToDailyForm({"user": self.user, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        MoveBlockToDailyCommand(form).execute()

        existing_parent.refresh_from_db()
        existing_child.refresh_from_db()
        block.refresh_from_db()

        self.assertEqual(existing_child.parent, existing_parent)
        self.assertEqual(existing_parent.page, today_page)
        self.assertEqual(block.page, today_page)
        # All orders unique on target page
        orders = list(
            Block.objects.filter(page=today_page).values_list("order", flat=True)
        )
        self.assertEqual(len(orders), len(set(orders)))
