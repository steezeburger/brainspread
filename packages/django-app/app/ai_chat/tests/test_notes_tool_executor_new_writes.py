"""Tests for the bulk + scheduling write tools added on the
current-page-and-bulk branch:

- snooze_block, cancel_reminder
- bulk_set_block_type, tag_blocks, untag_blocks
- bulk_reschedule, create_blocks_bulk
- get_current_page (read, but new and routes through
  NotesToolExecutor.current_page_uuid)
"""

from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Dict

import pytz
from django.test import TestCase
from django.utils import timezone

from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.models import Block, Reminder
from knowledge.test.helpers import BlockFactory, PageFactory


def _writable(user, current_page_uuid: str | None = None) -> NotesToolExecutor:
    """Executor with writes allowed and auto-approve so tests don't need
    to navigate the approval pause flow — that flow is exercised in
    test_approval_flow.py / test_notes_tool_executor_writes.py."""
    return NotesToolExecutor(
        user,
        allow_writes=True,
        auto_approve_writes=True,
        current_page_uuid=current_page_uuid,
    )


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=dt_timezone.utc)


class SnoozeBlockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="snooze@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.scheduled_block = BlockFactory(
            user=cls.user,
            page=cls.page,
            content="needs work",
            block_type="todo",
            scheduled_for=date(2025, 6, 1),
        )
        cls.reminder = Reminder.objects.create(
            block=cls.scheduled_block,
            fire_at=_utc(datetime(2025, 6, 1, 9, 0)),
            channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
        )
        cls.unscheduled_block = BlockFactory(
            user=cls.user, page=cls.page, content="floating", block_type="todo"
        )

    def test_shifts_scheduled_for_by_days_and_reminder_by_full_delta(self):
        ex = _writable(self.user)
        result = ex.execute(
            "snooze_block",
            {"block_uuid": str(self.scheduled_block.uuid), "days": 2, "hours": 1},
        )

        self.assertTrue(result.get("snoozed"))
        self.scheduled_block.refresh_from_db()
        self.reminder.refresh_from_db()
        self.assertEqual(self.scheduled_block.scheduled_for, date(2025, 6, 3))
        self.assertEqual(self.reminder.fire_at, _utc(datetime(2025, 6, 3, 10, 0)))

    def test_hours_only_shifts_reminder_not_date(self):
        ex = _writable(self.user)
        ex.execute(
            "snooze_block",
            {"block_uuid": str(self.scheduled_block.uuid), "hours": 3},
        )

        self.scheduled_block.refresh_from_db()
        self.reminder.refresh_from_db()
        self.assertEqual(self.scheduled_block.scheduled_for, date(2025, 6, 1))
        self.assertEqual(self.reminder.fire_at, _utc(datetime(2025, 6, 1, 12, 0)))

    def test_errors_on_block_with_no_schedule(self):
        ex = _writable(self.user)
        result = ex.execute(
            "snooze_block",
            {"block_uuid": str(self.unscheduled_block.uuid), "days": 1},
        )
        self.assertIn("error", result)

    def test_errors_when_neither_days_nor_hours(self):
        ex = _writable(self.user)
        result = ex.execute(
            "snooze_block",
            {"block_uuid": str(self.scheduled_block.uuid), "days": 0, "hours": 0},
        )
        self.assertIn("error", result)


class CancelReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="cancel@example.com", timezone="UTC")
        cls.other = UserFactory(email="cancel-other@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Tasks")
        cls.block = BlockFactory(
            user=cls.user,
            page=cls.page,
            block_type="todo",
            scheduled_for=date(2025, 6, 1),
        )

    def setUp(self):
        # Re-create the reminder per test so test independence isn't
        # broken by the prior test cancelling it.
        self.reminder = Reminder.objects.create(
            block=self.block,
            fire_at=_utc(datetime(2025, 6, 1, 9, 0)),
            channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
        )

    def test_cancels_pending_reminder_and_keeps_schedule(self):
        ex = _writable(self.user)
        result = ex.execute(
            "cancel_reminder", {"reminder_uuid": str(self.reminder.uuid)}
        )

        self.assertTrue(result.get("cancelled"))
        self.assertEqual(result["status"], Reminder.STATUS_CANCELLED)
        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_CANCELLED)
        self.assertIsNotNone(self.reminder.sent_at)
        # Schedule is untouched.
        self.block.refresh_from_db()
        self.assertEqual(self.block.scheduled_for, date(2025, 6, 1))

    def test_refuses_already_sent_reminder(self):
        self.reminder.status = Reminder.STATUS_SENT
        self.reminder.sent_at = timezone.now()
        self.reminder.save(update_fields=["status", "sent_at"])

        ex = _writable(self.user)
        result = ex.execute(
            "cancel_reminder", {"reminder_uuid": str(self.reminder.uuid)}
        )
        self.assertIn("error", result)

    def test_user_isolation(self):
        other_block = BlockFactory(
            user=self.other,
            page=PageFactory(user=self.other, title="Other"),
            block_type="todo",
        )
        other_reminder = Reminder.objects.create(
            block=other_block,
            fire_at=_utc(datetime(2025, 6, 1, 9, 0)),
            channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
        )

        ex = _writable(self.user)
        result = ex.execute(
            "cancel_reminder", {"reminder_uuid": str(other_reminder.uuid)}
        )
        self.assertIn("error", result)
        other_reminder.refresh_from_db()
        self.assertEqual(other_reminder.status, Reminder.STATUS_PENDING)


class BulkSetBlockTypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="bulk-type@example.com")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.b1 = BlockFactory(user=cls.user, page=cls.page, block_type="todo")
        cls.b2 = BlockFactory(user=cls.user, page=cls.page, block_type="doing")
        cls.b3 = BlockFactory(user=cls.user, page=cls.page, block_type="bullet")

    def test_flips_many_blocks_at_once(self):
        ex = _writable(self.user)
        result = ex.execute(
            "bulk_set_block_type",
            {
                "block_uuids": [str(self.b1.uuid), str(self.b2.uuid)],
                "new_type": "done",
            },
        )

        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(result["failed"], [])
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.b3.refresh_from_db()
        self.assertEqual(self.b1.block_type, "done")
        self.assertEqual(self.b2.block_type, "done")
        self.assertIsNotNone(self.b1.completed_at)
        self.assertEqual(self.b3.block_type, "bullet")

    def test_reports_failures_per_uuid(self):
        ex = _writable(self.user)
        bogus = "00000000-0000-0000-0000-000000000000"
        result = ex.execute(
            "bulk_set_block_type",
            {
                "block_uuids": [str(self.b1.uuid), bogus],
                "new_type": "done",
            },
        )

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["block_uuid"], bogus)

    def test_invalid_block_type_rejected(self):
        ex = _writable(self.user)
        result = ex.execute(
            "bulk_set_block_type",
            {"block_uuids": [str(self.b1.uuid)], "new_type": "nonsense"},
        )
        self.assertIn("error", result)


class TagBlocksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="tag@example.com")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.tag_a = PageFactory(user=cls.user, title="topic-a", slug="topic-a")
        cls.tag_b = PageFactory(user=cls.user, title="topic-b", slug="topic-b")
        cls.b1 = BlockFactory(user=cls.user, page=cls.page, content="one")
        cls.b2 = BlockFactory(user=cls.user, page=cls.page, content="two")

    def test_adds_tags_idempotently(self):
        ex = _writable(self.user)
        ex.execute(
            "tag_blocks",
            {
                "block_uuids": [str(self.b1.uuid), str(self.b2.uuid)],
                "page_uuids": [str(self.tag_a.uuid), str(self.tag_b.uuid)],
            },
        )

        self.assertSetEqual(
            {str(u) for u in self.b1.pages.values_list("uuid", flat=True)},
            {str(self.tag_a.uuid), str(self.tag_b.uuid)},
        )
        self.assertSetEqual(
            {str(u) for u in self.b2.pages.values_list("uuid", flat=True)},
            {str(self.tag_a.uuid), str(self.tag_b.uuid)},
        )

        # Repeat is a no-op.
        ex.execute(
            "tag_blocks",
            {
                "block_uuids": [str(self.b1.uuid)],
                "page_uuids": [str(self.tag_a.uuid)],
            },
        )
        self.assertEqual(self.b1.pages.count(), 2)

    def test_untag_removes_specified_pages_only(self):
        self.b1.pages.add(self.tag_a, self.tag_b)
        ex = _writable(self.user)
        ex.execute(
            "untag_blocks",
            {
                "block_uuids": [str(self.b1.uuid)],
                "page_uuids": [str(self.tag_a.uuid)],
            },
        )

        self.assertSetEqual(
            {str(u) for u in self.b1.pages.values_list("uuid", flat=True)},
            {str(self.tag_b.uuid)},
        )


class BulkRescheduleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="bulk-resched@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.b1 = BlockFactory(
            user=cls.user,
            page=cls.page,
            block_type="todo",
            scheduled_for=date(2025, 6, 1),
        )
        cls.b2 = BlockFactory(
            user=cls.user,
            page=cls.page,
            block_type="todo",
            scheduled_for=date(2025, 6, 5),
        )

    def test_moves_blocks_and_shifts_per_block_reminder(self):
        Reminder.objects.create(
            block=self.b1,
            fire_at=_utc(datetime(2025, 6, 1, 9, 0)),
            channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
        )
        ex = _writable(self.user)
        result = ex.execute(
            "bulk_reschedule",
            {
                "block_uuids": [str(self.b1.uuid), str(self.b2.uuid)],
                "new_date": "2025-06-10",
            },
        )

        self.assertEqual(result["updated_count"], 2)
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertEqual(self.b1.scheduled_for, date(2025, 6, 10))
        self.assertEqual(self.b2.scheduled_for, date(2025, 6, 10))
        # b1 was June 1, shifted +9 days to June 10. Reminder fire_at
        # should also shift +9 days, preserving the 09:00 time.
        reminder = self.b1.reminders.get()
        self.assertEqual(reminder.fire_at, _utc(datetime(2025, 6, 10, 9, 0)))

    def test_accepts_relative_date_token(self):
        ex = _writable(self.user)
        result = ex.execute(
            "bulk_reschedule",
            {"block_uuids": [str(self.b1.uuid)], "new_date": "+7d"},
        )
        self.assertEqual(result["updated_count"], 1)


class CreateBlocksBulkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="bulk-create@example.com")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.parent = BlockFactory(
            user=cls.user, page=cls.page, content="parent", block_type="bullet"
        )

    def test_creates_under_parent_in_order(self):
        ex = _writable(self.user)
        result = ex.execute(
            "create_blocks_bulk",
            {
                "parent_uuid": str(self.parent.uuid),
                "blocks": [
                    {"content": "buy milk", "block_type": "todo"},
                    {"content": "call dentist", "block_type": "todo"},
                    {"content": "polish deck"},
                ],
            },
        )

        self.assertEqual(result["created_count"], 3)
        children = list(self.parent.children.all().order_by("order"))
        self.assertEqual(len(children), 3)
        self.assertEqual(
            [b.content for b in children],
            ["buy milk", "call dentist", "polish deck"],
        )
        self.assertEqual(
            [b.block_type for b in children],
            ["todo", "todo", "bullet"],
        )

    def test_creates_at_page_root_when_only_page_given(self):
        ex = _writable(self.user)
        result = ex.execute(
            "create_blocks_bulk",
            {
                "page_uuid": str(self.page.uuid),
                "blocks": [{"content": "root note"}],
            },
        )
        self.assertEqual(result["created_count"], 1)
        # Created at root level (no parent) — verify by fetching the new block.
        new_block = Block.objects.get(uuid=result["blocks"][0]["block_uuid"])
        self.assertIsNone(new_block.parent_id)

    def test_requires_target(self):
        ex = _writable(self.user)
        result = ex.execute(
            "create_blocks_bulk",
            {"blocks": [{"content": "orphan"}]},
        )
        self.assertIn("error", result)

    def test_caps_batch_size(self):
        ex = _writable(self.user)
        result = ex.execute(
            "create_blocks_bulk",
            {
                "parent_uuid": str(self.parent.uuid),
                "blocks": [{"content": f"row {i}"} for i in range(51)],
            },
        )
        self.assertIn("error", result)


class GetCurrentPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="currpage@example.com")
        cls.page = PageFactory(user=cls.user, title="Project Alpha")
        cls.root_a = BlockFactory(user=cls.user, page=cls.page, content="root one")
        cls.child = BlockFactory(
            user=cls.user, page=cls.page, parent=cls.root_a, content="child"
        )
        cls.root_b = BlockFactory(user=cls.user, page=cls.page, content="root two")

    def test_returns_page_when_executor_has_uuid(self):
        ex = _writable(self.user, current_page_uuid=str(self.page.uuid))
        result = ex.execute("get_current_page", {})

        self.assertEqual(result["page"]["uuid"], str(self.page.uuid))
        self.assertEqual(result["page"]["title"], "Project Alpha")
        # Only root blocks — child is excluded.
        contents = [b["content"] for b in result["blocks"]]
        self.assertEqual(contents, ["root one", "root two"])

    def test_errors_when_no_current_page(self):
        ex = _writable(self.user, current_page_uuid=None)
        result = ex.execute("get_current_page", {})
        self.assertIn("error", result)

    def test_user_isolation(self):
        other_user = UserFactory(email="other-curr@example.com")
        ex = _writable(other_user, current_page_uuid=str(self.page.uuid))
        result = ex.execute("get_current_page", {})
        self.assertIn("error", result)


class NewToolRegistrationTests(TestCase):
    """Smoke check: is_known + schema list reflect the new tools."""

    def setUp(self):
        self.user = UserFactory(email="reg-new@example.com")

    def test_is_known_for_new_writes(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)
        for name in (
            "snooze_block",
            "cancel_reminder",
            "bulk_set_block_type",
            "tag_blocks",
            "untag_blocks",
            "bulk_reschedule",
            "create_blocks_bulk",
        ):
            self.assertTrue(ex.is_known(name), name)
            self.assertTrue(ex.requires_approval(name), name)

    def test_get_current_page_is_read_only(self):
        ex = NotesToolExecutor(self.user, allow_writes=False)
        self.assertTrue(ex.is_known("get_current_page"))
        self.assertFalse(ex.requires_approval("get_current_page"))

    def test_anthropic_schema_includes_new_tools(self):
        from ai_chat.tools.notes_tools import anthropic_notes_tools

        names = {t["name"] for t in anthropic_notes_tools(include_writes=True)}
        for name in (
            "snooze_block",
            "cancel_reminder",
            "bulk_set_block_type",
            "tag_blocks",
            "untag_blocks",
            "bulk_reschedule",
            "create_blocks_bulk",
            "get_current_page",
        ):
            self.assertIn(name, names)


# Defensively reference symbols imported but only used inside tests so
# linters don't trim them (pytz / time are used in helper datetimes).
_ = (Any, Dict, pytz, time, timedelta)
