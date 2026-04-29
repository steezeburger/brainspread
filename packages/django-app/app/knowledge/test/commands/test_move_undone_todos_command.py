from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.test import TestCase

from knowledge.commands import MoveUndoneTodosCommand
from knowledge.forms import MoveUndoneTodosForm
from knowledge.models import Block

from ..helpers import BlockFactory, PageFactory, UserFactory


def _utc_noon(d: date) -> datetime:
    """Helper: aware UTC datetime at noon on the given date.

    Used to feed core.helpers.timezone.now() while mocking, so that
    today_for_user(user) resolves to the target date for tests.
    """
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class TestMoveUndoneTodosCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    @patch("core.helpers.timezone")
    def test_should_move_undone_todos_to_bottom_of_target_page(self, mock_timezone):
        """Test that moved undone TODOs are placed at the bottom of the target page"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create a daily note page from yesterday with undone TODOs
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2025-06-29",
            slug="2025-06-29",
        )

        # Create some blocks on yesterday's page
        BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="DONE completed task",
            block_type="done",
            order=1,
        )
        todo1 = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO undone task 1",
            block_type="todo",
            order=2,
        )
        todo2 = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO undone task 2",
            block_type="todo",
            order=3,
        )

        # Create today's page with existing blocks
        today_page = PageFactory(
            user=self.user,
            date=today,
            page_type="daily",
            title="2025-06-30",
            slug="2025-06-30",
        )

        # Create some existing blocks on today's page
        existing_block1 = BlockFactory(
            user=self.user,
            page=today_page,
            content="Existing block 1",
            block_type="bullet",
            order=1,
        )
        existing_block2 = BlockFactory(
            user=self.user,
            page=today_page,
            content="Existing block 2",
            block_type="bullet",
            order=2,
        )

        # Execute the move command
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify the result
        self.assertEqual(result["moved_count"], 2)
        self.assertEqual(result["target_page"]["uuid"], str(today_page.uuid))
        self.assertIn("2 undone TODOs", result["message"])

        # Refresh blocks from database
        todo1.refresh_from_db()
        todo2.refresh_from_db()

        # Verify that moved TODOs are now on today's page
        self.assertEqual(todo1.page, today_page)
        self.assertEqual(todo2.page, today_page)

        # Verify that moved TODOs are placed at the bottom (after existing blocks)
        all_blocks = Block.objects.filter(page=today_page, parent=None).order_by(
            "order"
        )
        block_orders = [block.order for block in all_blocks]

        # Should be: existing_block1 (order 1), existing_block2 (order 2), todo1 (order 3), todo2 (order 4)
        self.assertEqual(block_orders, [1, 2, 3, 4])
        self.assertEqual(all_blocks[2], todo1)  # Third block should be first moved TODO
        self.assertEqual(
            all_blocks[3], todo2
        )  # Fourth block should be second moved TODO

    @patch("core.helpers.timezone")
    def test_should_not_move_completed_todos(self, mock_timezone):
        """Test that completed (DONE) TODOs are not moved"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create yesterday's page with both undone and done TODOs
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2025-06-29",
            slug="2025-06-29",
        )

        done_todo = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="DONE completed task",
            block_type="done",
            order=1,
        )
        undone_todo = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO undone task",
            block_type="todo",
            order=2,
        )

        # Execute the move command
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify only the undone TODO was moved
        self.assertEqual(result["moved_count"], 1)

        # Refresh from database
        done_todo.refresh_from_db()
        undone_todo.refresh_from_db()

        # DONE todo should still be on yesterday's page
        self.assertEqual(done_todo.page, yesterday_page)

        # Undone todo should be moved to today's page
        self.assertNotEqual(undone_todo.page, yesterday_page)

    @patch("core.helpers.timezone")
    def test_should_return_no_todos_message_when_none_found(self, mock_timezone):
        """Test that appropriate message is returned when no undone TODOs are found"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create yesterday's page with only completed TODOs
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2025-06-29",
            slug="2025-06-29",
        )

        BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="DONE completed task",
            block_type="done",
            order=1,
        )

        # Execute the move command
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify no TODOs were moved
        self.assertEqual(result["moved_count"], 0)
        self.assertEqual(result["message"], "No undone TODOs found to move")

    @patch("core.helpers.timezone")
    def test_should_preserve_relative_order_of_moved_todos(self, mock_timezone):
        """Test that moved TODOs maintain their relative order from source pages"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create multiple daily pages with TODOs
        day1 = date(2025, 6, 27)
        day1_page = PageFactory(
            user=self.user,
            date=day1,
            page_type="daily",
            title="2025-06-27",
            slug="2025-06-27",
        )

        day2 = date(2025, 6, 28)
        day2_page = PageFactory(
            user=self.user,
            date=day2,
            page_type="daily",
            title="2025-06-28",
            slug="2025-06-28",
        )

        # Create TODOs on different days
        todo_day1_first = BlockFactory(
            user=self.user,
            page=day1_page,
            content="TODO from day 1, first",
            block_type="todo",
            order=1,
        )
        todo_day1_second = BlockFactory(
            user=self.user,
            page=day1_page,
            content="TODO from day 1, second",
            block_type="todo",
            order=2,
        )
        todo_day2_first = BlockFactory(
            user=self.user,
            page=day2_page,
            content="TODO from day 2, first",
            block_type="todo",
            order=1,
        )

        # Execute the move command
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify all TODOs were moved
        self.assertEqual(result["moved_count"], 3)

        # Refresh from database
        todo_day1_first.refresh_from_db()
        todo_day1_second.refresh_from_db()
        todo_day2_first.refresh_from_db()

        # All TODOs should now be on today's page
        today_page = result["target_page"]
        self.assertEqual(str(todo_day1_first.page.uuid), today_page["uuid"])
        self.assertEqual(str(todo_day1_second.page.uuid), today_page["uuid"])
        self.assertEqual(str(todo_day2_first.page.uuid), today_page["uuid"])

        # Verify the relative order is preserved (older dates first, then by original order)
        moved_blocks = Block.objects.filter(
            page__uuid=today_page["uuid"], parent=None
        ).order_by("order")
        expected_order = [todo_day1_first, todo_day1_second, todo_day2_first]

        for i, expected_block in enumerate(expected_order):
            self.assertEqual(moved_blocks[i], expected_block)

    @patch("core.helpers.timezone")
    def test_should_not_disrupt_nested_blocks_when_moving_todos(self, mock_timezone):
        """Test that moving TODOs doesn't affect nested block structure on target page"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create yesterday's page with undone TODOs
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2025-06-29",
            slug="2025-06-29",
        )

        todo_to_move = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO move me",
            block_type="todo",
            order=1,
        )

        # Create today's page with nested blocks
        today_page = PageFactory(
            user=self.user,
            date=today,
            page_type="daily",
            title="2025-06-30",
            slug="2025-06-30",
        )

        # Create a parent block
        parent_block = BlockFactory(
            user=self.user,
            page=today_page,
            content="Parent block",
            block_type="bullet",
            order=1,
        )

        # Create nested children with higher order values than the parent
        child1 = BlockFactory(
            user=self.user,
            page=today_page,
            parent=parent_block,
            content="Nested child 1",
            block_type="bullet",
            order=2,
        )

        child2 = BlockFactory(
            user=self.user,
            page=today_page,
            parent=parent_block,
            content="Nested child 2",
            block_type="bullet",
            order=3,
        )

        # Execute the move command
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify the TODO was moved
        self.assertEqual(result["moved_count"], 1)

        # Refresh all blocks from database
        todo_to_move.refresh_from_db()
        parent_block.refresh_from_db()
        child1.refresh_from_db()
        child2.refresh_from_db()

        # Verify all blocks are on today's page
        self.assertEqual(todo_to_move.page, today_page)
        self.assertEqual(parent_block.page, today_page)
        self.assertEqual(child1.page, today_page)
        self.assertEqual(child2.page, today_page)

        # Verify nested structure is preserved
        self.assertIsNone(parent_block.parent)  # Parent should be root level
        self.assertEqual(
            child1.parent, parent_block
        )  # Child1 should still be nested under parent
        self.assertEqual(
            child2.parent, parent_block
        )  # Child2 should still be nested under parent

        # Verify the moved TODO was placed after ALL existing blocks (including nested ones)
        # The moved TODO should have an order higher than all existing blocks
        all_block_orders = [
            parent_block.order,
            child1.order,
            child2.order,
            todo_to_move.order,
        ]
        self.assertEqual(
            todo_to_move.order, max(all_block_orders)
        )  # Moved block should have highest order

        # Verify no order conflicts exist
        all_orders = Block.objects.filter(page=today_page).values_list(
            "order", flat=True
        )
        self.assertEqual(
            len(all_orders), len(set(all_orders))
        )  # All orders should be unique

    @patch("core.helpers.timezone")
    def test_should_move_undone_todos_to_specified_target_date(self, mock_timezone):
        """Test that undone TODOs can be moved to a specific target date"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create target date (2025-07-01)
        target_date = date(2025, 7, 1)

        # Create yesterday's page with undone TODOs
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
        )

        # Create undone TODOs from yesterday
        todo1 = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO task 1",
            block_type="todo",
            order=1,
        )
        todo2 = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO task 2",
            block_type="todo",
            order=2,
        )

        # Execute move command with target_date
        form_data = {"user": self.user, "target_date": target_date}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify TODOs were moved to target date
        self.assertEqual(result["moved_count"], 2)
        self.assertEqual(result["target_page"]["date"], target_date.isoformat())

        # Verify blocks are now on target date page
        todo1.refresh_from_db()
        todo2.refresh_from_db()
        self.assertEqual(todo1.page.date, target_date)
        self.assertEqual(todo2.page.date, target_date)

    @patch("core.helpers.timezone")
    def test_should_default_to_current_date_when_no_target_date_provided(
        self, mock_timezone
    ):
        """Test that command defaults to current date when target_date is not provided"""
        # Mock today's date to be 2025-06-30
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        # Create yesterday's page with undone TODO
        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
        )

        todo = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO task",
            block_type="todo",
            order=1,
        )

        # Execute move command without target_date
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Verify TODO was moved to current date (today)
        self.assertEqual(result["moved_count"], 1)
        self.assertEqual(result["target_page"]["date"], today.isoformat())

        # Verify block is now on today's page
        todo.refresh_from_db()
        self.assertEqual(todo.page.date, today)

    def test_form_should_accept_optional_target_date(self):
        """Test that MoveUndoneTodosForm accepts optional target_date field"""
        target_date = date(2025, 7, 1)

        # Test form with target_date
        form_data = {"user": self.user, "target_date": target_date}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["target_date"], target_date)

        # Test form without target_date
        form_data = {"user": self.user}
        form = MoveUndoneTodosForm(form_data)
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data.get("target_date"))

    def test_form_should_require_user_field(self):
        """Test that MoveUndoneTodosForm requires user field"""
        target_date = date(2025, 7, 1)

        # Test form without user
        form_data = {"target_date": target_date}
        form = MoveUndoneTodosForm(form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)

    @patch("core.helpers.timezone")
    def test_should_skip_dated_blocks_during_rollover(self, mock_timezone):
        """Dated blocks (scheduled_for set) stay on their original page —
        they surface via the overdue query instead."""
        today = date(2025, 6, 30)
        mock_timezone.now.return_value = _utc_noon(today)

        yesterday = date(2025, 6, 29)
        yesterday_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2025-06-29",
            slug="2025-06-29",
        )

        undated_todo = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO undated task",
            block_type="todo",
            order=1,
        )
        dated_todo = BlockFactory(
            user=self.user,
            page=yesterday_page,
            content="TODO dated task",
            block_type="todo",
            order=2,
            scheduled_for=yesterday,
        )

        form = MoveUndoneTodosForm({"user": self.user})
        self.assertTrue(form.is_valid())
        result = MoveUndoneTodosCommand(form).execute()

        self.assertEqual(result["moved_count"], 1)

        undated_todo.refresh_from_db()
        dated_todo.refresh_from_db()

        # Undated was moved; dated stayed put
        self.assertNotEqual(undated_todo.page, yesterday_page)
        self.assertEqual(dated_todo.page, yesterday_page)
