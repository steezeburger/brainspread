"""Tests for the read-only analytics tools added in #108.

Covers get_daily_pages_in_range, get_completion_stats, get_streaks,
find_stale_todos. Each test asserts the happy path plus an empty / edge
result so we trust both the query and the empty-shape contract.
"""

from datetime import date, datetime, time, timedelta

import pytz
from django.test import TestCase
from django.utils import timezone

from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.models import Block
from knowledge.test.helpers import BlockFactory, PageFactory


def _set_block_completed_at(block: Block, dt) -> None:
    """Bypass auto_now-style behaviour to set a precise completed_at."""
    Block.objects.filter(pk=block.pk).update(completed_at=dt)


def _set_block_created_at(block: Block, dt) -> None:
    Block.objects.filter(pk=block.pk).update(created_at=dt)


class GetDailyPagesInRangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="daily-range@example.com", timezone="UTC")
        cls.other = UserFactory(email="other-daily@example.com", timezone="UTC")
        cls.day_a = date(2025, 6, 1)
        cls.day_b = date(2025, 6, 2)
        cls.day_c = date(2025, 6, 5)
        cls.page_a = PageFactory(
            user=cls.user,
            page_type="daily",
            title="2025-06-01",
            slug="2025-06-01",
            date=cls.day_a,
        )
        cls.page_b = PageFactory(
            user=cls.user,
            page_type="daily",
            title="2025-06-02",
            slug="2025-06-02",
            date=cls.day_b,
        )
        cls.page_c = PageFactory(
            user=cls.user,
            page_type="daily",
            title="2025-06-05",
            slug="2025-06-05",
            date=cls.day_c,
        )
        cls.root_a = BlockFactory(
            user=cls.user, page=cls.page_a, content="june 1 root", block_type="bullet"
        )
        BlockFactory(
            user=cls.user,
            page=cls.page_a,
            parent=cls.root_a,
            content="june 1 child",
        )
        BlockFactory(
            user=cls.user, page=cls.page_b, content="june 2 root", block_type="bullet"
        )
        # Daily page belonging to another user — must not leak.
        other_page = PageFactory(
            user=cls.other,
            page_type="daily",
            title="2025-06-01-other",
            slug="2025-06-01-other",
            date=cls.day_a,
        )
        BlockFactory(user=cls.other, page=other_page, content="other user")

    def test_returns_pages_in_range_with_root_blocks_only(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_daily_pages_in_range",
            {"start_date": "2025-06-01", "end_date": "2025-06-03"},
        )

        self.assertEqual(result["count"], 2)
        dates = [r["date"] for r in result["results"]]
        self.assertEqual(dates, ["2025-06-01", "2025-06-02"])
        # June 1 page has one root block (the child must be excluded).
        june_1 = result["results"][0]
        self.assertEqual(len(june_1["root_blocks"]), 1)
        self.assertEqual(june_1["root_blocks"][0]["content"], "june 1 root")

    def test_empty_range_returns_no_results(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_daily_pages_in_range",
            {"start_date": "2025-07-01", "end_date": "2025-07-05"},
        )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["results"], [])

    def test_rejects_oversized_range(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_daily_pages_in_range",
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        )

        self.assertIn("error", result)
        self.assertIn("range too large", result["error"])

    def test_rejects_inverted_range(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_daily_pages_in_range",
            {"start_date": "2025-06-05", "end_date": "2025-06-01"},
        )

        self.assertIn("error", result)


class GetCompletionStatsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="completion-stats@example.com", timezone="UTC")
        cls.other = UserFactory(email="other-stats@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Inbox")

        # Three completions: two on day 1, one on day 3 of the window.
        cls.done_1 = BlockFactory(
            user=cls.user, page=cls.page, content="done a", block_type="done"
        )
        cls.done_2 = BlockFactory(
            user=cls.user, page=cls.page, content="done b", block_type="done"
        )
        cls.done_3 = BlockFactory(
            user=cls.user, page=cls.page, content="done c", block_type="done"
        )
        cls.wontdo_1 = BlockFactory(
            user=cls.user, page=cls.page, content="wontdo a", block_type="wontdo"
        )

        # Two new opens in the window.
        cls.todo_1 = BlockFactory(
            user=cls.user, page=cls.page, content="todo a", block_type="todo"
        )
        cls.doing_1 = BlockFactory(
            user=cls.user, page=cls.page, content="doing a", block_type="doing"
        )

        # Out of range — must not count.
        cls.todo_old = BlockFactory(
            user=cls.user, page=cls.page, content="ancient", block_type="todo"
        )

        # Different user — must not leak.
        other_page = PageFactory(user=cls.other, title="Other Inbox")
        cls.other_done = BlockFactory(
            user=cls.other,
            page=other_page,
            content="not mine",
            block_type="done",
        )

    def setUp(self):
        # Pin completion_at + created_at to deterministic UTC datetimes.
        utc = pytz.UTC
        in_window_day1 = utc.localize(datetime(2025, 6, 1, 9, 0))
        in_window_day1_b = utc.localize(datetime(2025, 6, 1, 18, 30))
        in_window_day3 = utc.localize(datetime(2025, 6, 3, 12, 0))
        out_of_window = utc.localize(datetime(2025, 5, 1, 12, 0))

        _set_block_completed_at(self.done_1, in_window_day1)
        _set_block_completed_at(self.done_2, in_window_day1_b)
        _set_block_completed_at(self.done_3, in_window_day3)
        _set_block_completed_at(self.wontdo_1, in_window_day3)
        _set_block_completed_at(self.other_done, in_window_day1)

        _set_block_created_at(self.todo_1, in_window_day1)
        _set_block_created_at(self.doing_1, in_window_day3)
        _set_block_created_at(self.todo_old, out_of_window)
        # done blocks created in window too — but only completion counts here
        _set_block_created_at(self.done_1, in_window_day1)
        _set_block_created_at(self.done_2, in_window_day1_b)
        _set_block_created_at(self.done_3, in_window_day3)
        _set_block_created_at(self.wontdo_1, in_window_day3)

    def test_counts_segregate_by_state_and_user(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_completion_stats",
            {"start_date": "2025-06-01", "end_date": "2025-06-05"},
        )

        self.assertEqual(result["counts"]["done"], 3)
        self.assertEqual(result["counts"]["wontdo"], 1)
        self.assertEqual(result["counts"]["todo"], 1)
        self.assertEqual(result["counts"]["doing"], 1)
        self.assertEqual(result["counts"]["later"], 0)

    def test_by_day_includes_zero_filled_dates(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_completion_stats",
            {"start_date": "2025-06-01", "end_date": "2025-06-05"},
        )

        by_day = {row["date"]: row["done_count"] for row in result["by_day"]}
        self.assertEqual(by_day["2025-06-01"], 2)
        self.assertEqual(by_day["2025-06-02"], 0)
        self.assertEqual(by_day["2025-06-03"], 1)
        self.assertEqual(by_day["2025-06-04"], 0)
        self.assertEqual(by_day["2025-06-05"], 0)

    def test_empty_window_returns_zeros(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_completion_stats",
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )

        for value in result["counts"].values():
            self.assertEqual(value, 0)
        self.assertEqual(len(result["by_day"]), 7)


class GetCompletionStatsTimezoneTests(TestCase):
    """A user in UTC-8 finishes a block at 2025-06-02 02:00 UTC. That's
    still 2025-06-01 in their local time, and the by_day breakdown must
    bucket the completion under June 1 — not June 2.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(
            email="tz-stats@example.com", timezone="America/Los_Angeles"
        )
        cls.page = PageFactory(user=cls.user, title="Inbox")
        cls.block = BlockFactory(
            user=cls.user, page=cls.page, content="late night", block_type="done"
        )

    def setUp(self):
        utc = pytz.UTC
        # 2025-06-02 02:00 UTC == 2025-06-01 19:00 PDT (during DST).
        late_night_utc = utc.localize(datetime(2025, 6, 2, 2, 0))
        _set_block_completed_at(self.block, late_night_utc)
        _set_block_created_at(self.block, late_night_utc)

    def test_completion_buckets_into_user_local_day(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute(
            "get_completion_stats",
            {"start_date": "2025-06-01", "end_date": "2025-06-03"},
        )

        by_day = {row["date"]: row["done_count"] for row in result["by_day"]}
        self.assertEqual(by_day["2025-06-01"], 1)
        self.assertEqual(by_day["2025-06-02"], 0)
        self.assertEqual(result["counts"]["done"], 1)


class GetStreaksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="streaks@example.com", timezone="UTC")

    def _make_daily_with_block(self, day):
        page = PageFactory(
            user=self.user,
            page_type="daily",
            title=str(day),
            slug=f"daily-{day}",
            date=day,
        )
        BlockFactory(user=self.user, page=page, content=f"entry for {day}")
        return page

    def test_journal_streak_three_days_active(self):
        as_of = date(2025, 6, 10)
        for offset in (0, 1, 2):
            self._make_daily_with_block(as_of - timedelta(days=offset))
        # Gap before
        self._make_daily_with_block(as_of - timedelta(days=4))

        executor = NotesToolExecutor(self.user)
        result = executor.execute(
            "get_streaks", {"kind": "journal", "as_of": as_of.isoformat()}
        )

        self.assertEqual(result["current_streak"], 3)
        self.assertEqual(result["longest_streak"], 3)
        self.assertEqual(result["last_active_date"], as_of.isoformat())

    def test_journal_streak_zero_when_today_inactive(self):
        as_of = date(2025, 6, 10)
        # Last active was yesterday — current streak is zero, longest is 1.
        self._make_daily_with_block(as_of - timedelta(days=1))

        executor = NotesToolExecutor(self.user)
        result = executor.execute(
            "get_streaks", {"kind": "journal", "as_of": as_of.isoformat()}
        )

        self.assertEqual(result["current_streak"], 0)
        self.assertEqual(result["longest_streak"], 1)
        self.assertEqual(
            result["last_active_date"], (as_of - timedelta(days=1)).isoformat()
        )

    def test_completion_streak_uses_completed_at(self):
        as_of = date(2025, 6, 10)
        page = PageFactory(user=self.user, title="Tasks")
        utc = pytz.UTC
        for offset in (0, 1):
            block = BlockFactory(user=self.user, page=page, block_type="done")
            _set_block_completed_at(
                block,
                utc.localize(
                    datetime.combine(as_of - timedelta(days=offset), time(15))
                ),
            )

        executor = NotesToolExecutor(self.user)
        result = executor.execute(
            "get_streaks", {"kind": "completion", "as_of": as_of.isoformat()}
        )

        self.assertEqual(result["current_streak"], 2)
        self.assertEqual(result["longest_streak"], 2)

    def test_completion_streak_returns_zero_with_no_data(self):
        executor = NotesToolExecutor(self.user)
        result = executor.execute(
            "get_streaks", {"kind": "completion", "as_of": "2025-06-10"}
        )

        self.assertEqual(result["current_streak"], 0)
        self.assertEqual(result["longest_streak"], 0)
        self.assertIsNone(result["last_active_date"])

    def test_invalid_kind_returns_error(self):
        executor = NotesToolExecutor(self.user)
        result = executor.execute("get_streaks", {"kind": "nonsense"})

        self.assertIn("error", result)


class FindStaleTodosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="stale-todos@example.com", timezone="UTC")
        cls.other = UserFactory(email="other-stale@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Inbox")
        # Stale: open todo, no schedule, created 30 days ago.
        cls.stale = BlockFactory(
            user=cls.user, page=cls.page, content="stale", block_type="todo"
        )
        # Not stale: created today.
        cls.fresh = BlockFactory(
            user=cls.user, page=cls.page, content="fresh", block_type="todo"
        )
        # Has a schedule — should be excluded.
        cls.scheduled = BlockFactory(
            user=cls.user,
            page=cls.page,
            content="scheduled",
            block_type="todo",
            scheduled_for=date(2025, 7, 1),
        )
        # Done — completed_at is set, should be excluded.
        cls.completed_done = BlockFactory(
            user=cls.user, page=cls.page, content="done already", block_type="done"
        )
        # Wrong block_type — only `todo` qualifies per the spec.
        cls.doing = BlockFactory(
            user=cls.user, page=cls.page, content="doing", block_type="doing"
        )
        # Other user — must not leak.
        other_page = PageFactory(user=cls.other, title="Inbox")
        cls.other_stale = BlockFactory(
            user=cls.other, page=other_page, content="not mine", block_type="todo"
        )

    def setUp(self):
        # Use times relative to "now" so the test is robust against the
        # real wall clock — `find_stale_todos` measures age from today.
        recent = timezone.now()
        # 30 days old: passes the default 14-day threshold but not 365.
        thirty_days_ago = recent - timedelta(days=30)
        _set_block_created_at(self.stale, thirty_days_ago)
        _set_block_created_at(self.fresh, recent)
        _set_block_created_at(self.scheduled, thirty_days_ago)
        _set_block_created_at(self.completed_done, thirty_days_ago)
        _set_block_created_at(self.doing, thirty_days_ago)
        _set_block_created_at(self.other_stale, thirty_days_ago)
        _set_block_completed_at(self.completed_done, recent)

    def test_returns_only_open_unscheduled_old_todos(self):
        executor = NotesToolExecutor(self.user)
        result = executor.execute("find_stale_todos", {"older_than_days": 14})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["content_preview"], "stale")
        self.assertGreaterEqual(result["results"][0]["age_days"], 14)

    def test_default_threshold_excludes_recent(self):
        executor = NotesToolExecutor(self.user)
        result = executor.execute("find_stale_todos", {})

        contents = {row["content_preview"] for row in result["results"]}
        self.assertIn("stale", contents)
        self.assertNotIn("fresh", contents)

    def test_threshold_too_high_returns_empty(self):
        executor = NotesToolExecutor(self.user)
        result = executor.execute("find_stale_todos", {"older_than_days": 365})

        self.assertEqual(result["count"], 0)


class AnalyticsToolRegistrationTests(TestCase):
    """The new tools should be visible to the executor and to the schema
    list — a skipped registration would silently disable them."""

    def setUp(self):
        self.user = UserFactory(email="reg@example.com")

    def test_is_known_for_each_new_tool(self):
        executor = NotesToolExecutor(self.user)
        for name in (
            "get_daily_pages_in_range",
            "get_completion_stats",
            "get_streaks",
            "find_stale_todos",
        ):
            self.assertTrue(executor.is_known(name), name)
            self.assertFalse(executor.requires_approval(name), name)

    def test_anthropic_schema_includes_new_tools(self):
        from ai_chat.tools.notes_tools import anthropic_notes_tools

        names = {t["name"] for t in anthropic_notes_tools()}
        self.assertIn("get_daily_pages_in_range", names)
        self.assertIn("get_completion_stats", names)
        self.assertIn("get_streaks", names)
        self.assertIn("find_stale_todos", names)
