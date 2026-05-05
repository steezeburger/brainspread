from datetime import date, datetime, time, timedelta

import pytz
from django.test import TestCase
from django.utils import timezone

from ai_chat.tools.notes_tool_executor import (
    NotesToolExecutor,
    _parse_relative_date,
    _resolve_reminder_time,
)
from ai_chat.tools.notes_tools import (
    NOTES_READ_TOOL_NAMES,
    NOTES_WRITE_TOOL_NAMES,
)
from core.test.helpers import UserFactory
from knowledge.models import Reminder
from knowledge.test.helpers import BlockFactory, PageFactory


class ParseRelativeDateTestCase(TestCase):
    def setUp(self):
        self.today = date(2026, 5, 1)

    def test_iso_passthrough(self):
        self.assertEqual(
            _parse_relative_date("2026-04-30", self.today), date(2026, 4, 30)
        )

    def test_today_keyword(self):
        self.assertEqual(_parse_relative_date("today", self.today), self.today)

    def test_tomorrow_keyword(self):
        self.assertEqual(_parse_relative_date("tomorrow", self.today), date(2026, 5, 2))

    def test_yesterday_keyword(self):
        self.assertEqual(
            _parse_relative_date("yesterday", self.today), date(2026, 4, 30)
        )

    def test_positive_day_offset(self):
        self.assertEqual(_parse_relative_date("+3d", self.today), date(2026, 5, 4))

    def test_negative_day_offset(self):
        self.assertEqual(_parse_relative_date("-2d", self.today), date(2026, 4, 29))

    def test_week_offset(self):
        self.assertEqual(_parse_relative_date("+1w", self.today), date(2026, 5, 8))

    def test_empty_returns_none(self):
        self.assertIsNone(_parse_relative_date("", self.today))
        self.assertIsNone(_parse_relative_date(None, self.today))

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            _parse_relative_date("not a date", self.today)


class SchedulingToolDiscoveryTestCase(TestCase):
    def test_new_tool_names_registered(self):
        # Read tools (no approval gate).
        for name in (
            "list_overdue_blocks",
            "list_pending_reminders",
            "list_scheduled_blocks",
        ):
            self.assertIn(name, NOTES_READ_TOOL_NAMES)
            self.assertNotIn(name, NOTES_WRITE_TOOL_NAMES)

        # Write tools (gated behind approval).
        for name in (
            "schedule_block",
            "clear_schedule",
            "set_block_type",
            "move_block_to_daily",
        ):
            self.assertIn(name, NOTES_WRITE_TOOL_NAMES)
            self.assertNotIn(name, NOTES_READ_TOOL_NAMES)

    def test_writes_require_approval_by_default(self):
        user = UserFactory(email="approval@example.com")
        ex = NotesToolExecutor(user, allow_writes=True)
        for name in (
            "schedule_block",
            "clear_schedule",
            "set_block_type",
            "move_block_to_daily",
        ):
            self.assertTrue(ex.requires_approval(name), name)

    def test_auto_approve_skips_gate(self):
        user = UserFactory(email="auto-approve@example.com")
        ex = NotesToolExecutor(user, allow_writes=True, auto_approve_writes=True)
        for name in (
            "schedule_block",
            "clear_schedule",
            "set_block_type",
            "move_block_to_daily",
        ):
            self.assertFalse(ex.requires_approval(name), name)

    def test_reads_known_without_writes(self):
        user = UserFactory(email="reads@example.com")
        ex = NotesToolExecutor(user, allow_writes=False)
        for name in (
            "list_overdue_blocks",
            "list_pending_reminders",
            "list_scheduled_blocks",
        ):
            self.assertTrue(ex.is_known(name), name)
            self.assertFalse(ex.requires_approval(name), name)


class ScheduleBlockToolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="sched@example.com", timezone="America/New_York")
        cls.other_user = UserFactory(email="sched-other@example.com")
        cls.page = PageFactory(user=cls.user, title="Inbox", slug="inbox")
        cls.block = BlockFactory(
            user=cls.user, page=cls.page, content="ship feature", block_type="todo"
        )

    def test_sets_scheduled_for(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "schedule_block",
            {"block_uuid": str(self.block.uuid), "scheduled_for": "2026-06-15"},
        )

        self.assertTrue(result.get("scheduled"))
        self.assertEqual(result["block"]["scheduled_for"], "2026-06-15")
        self.block.refresh_from_db()
        self.assertEqual(self.block.scheduled_for, date(2026, 6, 15))

    def test_creates_reminder_when_time_provided(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "schedule_block",
            {
                "block_uuid": str(self.block.uuid),
                "scheduled_for": "2026-06-15",
                "reminder_time": "09:30",
            },
        )

        self.assertTrue(result.get("scheduled"))
        reminders = Reminder.objects.filter(block=self.block)
        self.assertEqual(reminders.count(), 1)
        # User is in America/New_York; 09:30 local on 2026-06-15.
        expected = (
            pytz.timezone("America/New_York")
            .localize(datetime.combine(date(2026, 6, 15), time(9, 30)))
            .astimezone(pytz.UTC)
        )
        self.assertEqual(reminders.first().fire_at, expected)

    def test_resolves_relative_dates(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "schedule_block",
            {"block_uuid": str(self.block.uuid), "scheduled_for": "tomorrow"},
        )

        self.assertTrue(result.get("scheduled"))
        self.block.refresh_from_db()
        # Tomorrow in user's timezone — assert it's exactly one day after
        # today_for_user, which is what the tool uses.

        self.assertEqual(
            self.block.scheduled_for, self.user.today() + timedelta(days=1)
        )

    def test_rejects_other_users_block(self):
        ex = NotesToolExecutor(self.other_user, allow_writes=True)

        result = ex.execute(
            "schedule_block",
            {"block_uuid": str(self.block.uuid), "scheduled_for": "2026-06-15"},
        )

        self.assertIn("error", result)
        self.block.refresh_from_db()
        self.assertIsNone(self.block.scheduled_for)

    def test_rejects_garbage_date(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "schedule_block",
            {"block_uuid": str(self.block.uuid), "scheduled_for": "next thursday"},
        )

        self.assertIn("error", result)


class ClearScheduleToolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="clear@example.com")
        cls.page = PageFactory(user=cls.user)

    def test_clears_schedule_and_pending_reminder(self):
        block = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 5, 30)
        )
        Reminder.objects.create(
            block=block, fire_at=timezone.now() + timedelta(hours=1)
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("clear_schedule", {"block_uuid": str(block.uuid)})

        self.assertTrue(result.get("cleared"))
        block.refresh_from_db()
        self.assertIsNone(block.scheduled_for)
        self.assertEqual(
            Reminder.objects.filter(block=block, sent_at__isnull=True).count(), 0
        )


class SetBlockTypeToolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="type@example.com")
        cls.page = PageFactory(user=cls.user)

    def test_marks_todo_done_and_sets_completed_at(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="TODO ship it", block_type="todo"
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "set_block_type",
            {"block_uuid": str(block.uuid), "block_type": "done"},
        )

        self.assertTrue(result.get("updated"))
        block.refresh_from_db()
        self.assertEqual(block.block_type, "done")
        self.assertIsNotNone(block.completed_at)
        # Prefix swap happens in SetBlockTypeCommand.
        self.assertTrue(block.content.lower().startswith("done"))

    def test_rejects_invalid_block_type(self):
        block = BlockFactory(user=self.user, page=self.page, block_type="todo")
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "set_block_type",
            {"block_uuid": str(block.uuid), "block_type": "not-a-type"},
        )

        self.assertIn("error", result)
        block.refresh_from_db()
        self.assertEqual(block.block_type, "todo")


class MoveBlockToDailyToolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="move-daily@example.com")
        cls.page = PageFactory(user=cls.user, title="Project", slug="project")

    def test_moves_block_to_daily(self):
        block = BlockFactory(user=self.user, page=self.page, content="meeting prep")
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "move_block_to_daily",
            {"block_uuid": str(block.uuid), "target_date": "2026-06-15"},
        )

        self.assertTrue(result.get("moved"))
        self.assertEqual(result["target_page"]["page_type"], "daily")
        # The source page must show up in affected_page_uuids so the
        # frontend can refresh whichever page the user has open.
        self.assertIn(str(self.page.uuid), result["affected_page_uuids"])
        block.refresh_from_db()
        self.assertEqual(block.page.date, date(2026, 6, 15))

    def test_default_target_is_today(self):

        block = BlockFactory(user=self.user, page=self.page, content="urgent")
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("move_block_to_daily", {"block_uuid": str(block.uuid)})

        self.assertTrue(result.get("moved"))
        block.refresh_from_db()
        self.assertEqual(block.page.date, self.user.today())


class ListReadToolsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="list@example.com")
        cls.other_user = UserFactory(email="list-other@example.com")
        cls.page = PageFactory(user=cls.user, title="Project", slug="project")
        cls.other_page = PageFactory(user=cls.other_user, title="Other", slug="other")

    def test_list_overdue_blocks_filters_by_user_and_today(self):

        today = self.user.today()
        BlockFactory(
            user=self.user,
            page=self.page,
            content="overdue todo",
            block_type="todo",
            scheduled_for=today - timedelta(days=2),
        )
        BlockFactory(
            user=self.user,
            page=self.page,
            content="future todo",
            block_type="todo",
            scheduled_for=today + timedelta(days=2),
        )
        # Other user's overdue must NOT leak through.
        BlockFactory(
            user=self.other_user,
            page=self.other_page,
            content="someone else overdue",
            block_type="todo",
            scheduled_for=today - timedelta(days=2),
        )
        ex = NotesToolExecutor(self.user)

        result = ex.execute("list_overdue_blocks", {})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["content"], "overdue todo")
        self.assertEqual(result["results"][0]["page_title"], "Project")

    def test_list_pending_reminders_excludes_sent(self):
        block = BlockFactory(user=self.user, page=self.page, content="ping me")
        pending = Reminder.objects.create(
            block=block, fire_at=timezone.now() + timedelta(hours=2)
        )
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(hours=1),
            sent_at=timezone.now(),
            status=Reminder.STATUS_SENT,
        )
        # Other user's reminder must not leak.
        other_block = BlockFactory(user=self.other_user, page=self.other_page)
        Reminder.objects.create(
            block=other_block, fire_at=timezone.now() + timedelta(hours=3)
        )
        ex = NotesToolExecutor(self.user)

        result = ex.execute("list_pending_reminders", {})

        self.assertEqual(result["count"], 1)
        entry = result["results"][0]
        self.assertEqual(entry["uuid"], str(pending.uuid))
        self.assertEqual(entry["block_content"], "ping me")
        self.assertEqual(entry["page_title"], "Project")

    def test_list_scheduled_blocks_returns_range(self):

        today = self.user.today()
        in_range = BlockFactory(
            user=self.user,
            page=self.page,
            content="in range",
            scheduled_for=today + timedelta(days=3),
        )
        BlockFactory(
            user=self.user,
            page=self.page,
            content="too far",
            scheduled_for=today + timedelta(days=60),
        )
        ex = NotesToolExecutor(self.user)

        result = ex.execute(
            "list_scheduled_blocks",
            {"start_date": "today", "end_date": "+30d"},
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["block_uuid"], str(in_range.uuid))

    def test_list_scheduled_blocks_rejects_inverted_range(self):
        ex = NotesToolExecutor(self.user)
        result = ex.execute(
            "list_scheduled_blocks",
            {"start_date": "2026-06-15", "end_date": "2026-06-01"},
        )
        self.assertIn("error", result)


class GetCurrentTimeToolTestCase(TestCase):
    def test_returns_user_local_now(self):
        user = UserFactory(email="now@example.com", timezone="America/New_York")
        ex = NotesToolExecutor(user)

        result = ex.execute("get_current_time", {})

        self.assertEqual(result["timezone"], "America/New_York")
        # Sanity-check that the response is a real ISO timestamp matching
        # America/New_York (the offset string varies by DST so just check
        # a tz suffix is present).
        self.assertIn("T", result["now"])
        self.assertRegex(result["time"], r"^\d{2}:\d{2}$")
        self.assertRegex(result["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(
            result["weekday"],
            {
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            },
        )

    def test_falls_back_to_utc_for_unset_tz(self):
        user = UserFactory(email="no-tz@example.com", timezone="")
        ex = NotesToolExecutor(user)

        result = ex.execute("get_current_time", {})

        self.assertEqual(result["timezone"], "UTC")


class ResolveReminderTimeTestCase(TestCase):
    def setUp(self):
        self.user = UserFactory(email="rt@example.com", timezone="UTC")

    def test_empty_returns_none_pair(self):
        self.assertEqual(_resolve_reminder_time(None, self.user), (None, None))
        self.assertEqual(_resolve_reminder_time("", self.user), (None, None))

    def test_wallclock_passes_through(self):
        d, t = _resolve_reminder_time("09:30", self.user)
        self.assertIsNone(d)
        self.assertEqual(t, "09:30")

    def test_relative_minutes_returns_now_plus_offset(self):
        d, t = _resolve_reminder_time("+5m", self.user)
        # Date should be today (in UTC for this user); time should be
        # within a minute of now+5m.
        now_utc = timezone.now()
        expected = now_utc + timedelta(minutes=5)
        self.assertEqual(d, expected.date())
        # Allow a 1-minute drift since clock advances during the test.
        actual = datetime.strptime(t, "%H:%M").replace(
            year=expected.year, month=expected.month, day=expected.day
        )
        actual = pytz.UTC.localize(actual)
        diff = abs((actual - expected.replace(second=0, microsecond=0)).total_seconds())
        self.assertLess(diff, 90)

    def test_relative_hours(self):
        d, _ = _resolve_reminder_time("+2h", self.user)
        expected = (timezone.now() + timedelta(hours=2)).date()
        self.assertEqual(d, expected)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            _resolve_reminder_time("not a time", self.user)


class ScheduleBlockRelativeTimeTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="rel-time@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def test_relative_minute_offset_creates_reminder_at_now_plus_n(self):
        block = BlockFactory(user=self.user, page=self.page, content="leave soon")
        ex = NotesToolExecutor(self.user, allow_writes=True)
        before = timezone.now()

        result = ex.execute(
            "schedule_block",
            {
                "block_uuid": str(block.uuid),
                "scheduled_for": "today",
                "reminder_time": "+3m",
            },
        )

        self.assertTrue(result.get("scheduled"))
        reminder = Reminder.objects.get(block=block)
        # The reminder fires within ~3m of when we called the tool
        # (allow a generous bound for slow CI).
        delta = (reminder.fire_at - before).total_seconds()
        self.assertGreater(delta, 60)
        self.assertLess(delta, 240)
