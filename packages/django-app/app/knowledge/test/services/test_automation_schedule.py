from datetime import datetime
from datetime import timezone as dt_timezone

import pytz
from django.test import SimpleTestCase

from knowledge.services.automation_schedule import (
    CronError,
    is_due,
    parse_cron,
    previous_slot,
)
from knowledge.services.automation_spec import (
    SCHEDULE_CRON,
    SCHEDULE_DAILY,
    SCHEDULE_EVERY,
    SCHEDULE_HOURLY,
    SCHEDULE_WEEKLY,
    ScheduleSpec,
)

UTC = dt_timezone.utc
LA = pytz.timezone("America/Los_Angeles")


def _every(minutes: int) -> ScheduleSpec:
    return ScheduleSpec(raw="", kind=SCHEDULE_EVERY, interval_minutes=minutes)


def _daily(hour: int, minute: int = 0) -> ScheduleSpec:
    return ScheduleSpec(raw="", kind=SCHEDULE_DAILY, hour=hour, minute=minute)


class TestPreviousSlot(SimpleTestCase):
    def test_every_15m_floors_to_quarter_hour(self):
        now = datetime(2026, 6, 27, 10, 7, 33, tzinfo=UTC)
        slot = previous_slot(_every(15), now, UTC)
        self.assertEqual(slot, datetime(2026, 6, 27, 10, 0, tzinfo=UTC))

    def test_hourly_floors_to_top_of_hour(self):
        now = datetime(2026, 6, 27, 10, 42, tzinfo=UTC)
        spec = ScheduleSpec(raw="", kind=SCHEDULE_HOURLY, minute=0)
        self.assertEqual(
            previous_slot(spec, now, UTC), datetime(2026, 6, 27, 10, 0, tzinfo=UTC)
        )

    def test_daily_resolves_in_owner_timezone(self):
        # 2026-06-27 14:30 UTC == 07:30 in LA; the 6:00 LA slot has passed
        # today, so the slot is 6:00 LA == 13:00 UTC.
        now = datetime(2026, 6, 27, 14, 30, tzinfo=UTC)
        slot = previous_slot(_daily(6), now, LA)
        self.assertEqual(slot, datetime(2026, 6, 27, 13, 0, tzinfo=UTC))

    def test_daily_before_todays_slot_uses_yesterday(self):
        # 11:00 UTC == 04:00 LA — before 6:00, so slot = yesterday 6:00 LA.
        now = datetime(2026, 6, 27, 11, 0, tzinfo=UTC)
        slot = previous_slot(_daily(6), now, LA)
        self.assertEqual(slot, datetime(2026, 6, 26, 13, 0, tzinfo=UTC))

    def test_weekly_most_recent_weekday(self):
        # 2026-06-27 is a Saturday. weekly mon 9:00 UTC → Monday 2026-06-22.
        now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)
        spec = ScheduleSpec(raw="", kind=SCHEDULE_WEEKLY, weekday=0, hour=9, minute=0)
        slot = previous_slot(spec, now, UTC)
        self.assertEqual(slot, datetime(2026, 6, 22, 9, 0, tzinfo=UTC))

    def test_cron_previous_matching_minute(self):
        now = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)
        spec = ScheduleSpec(raw="", kind=SCHEDULE_CRON, cron="*/15 * * * *")
        self.assertEqual(
            previous_slot(spec, now, UTC), datetime(2026, 6, 27, 10, 0, tzinfo=UTC)
        )

    def test_cron_weekday_window(self):
        # Saturday scan back to Friday 06:00 for a weekday-only cron.
        now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)  # Saturday
        spec = ScheduleSpec(raw="", kind=SCHEDULE_CRON, cron="0 6 * * 1-5")
        self.assertEqual(
            previous_slot(spec, now, UTC), datetime(2026, 6, 26, 6, 0, tzinfo=UTC)
        )

    def test_malformed_cron_yields_no_slot(self):
        now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)
        spec = ScheduleSpec(raw="", kind=SCHEDULE_CRON, cron="banana * * * *")
        self.assertIsNone(previous_slot(spec, now, UTC))


class TestIsDue(SimpleTestCase):
    def test_never_run_is_due(self):
        now = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)
        self.assertTrue(is_due(_every(15), None, now, UTC))

    def test_ran_after_slot_is_not_due(self):
        now = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)
        last = datetime(2026, 6, 27, 10, 1, tzinfo=UTC)
        self.assertFalse(is_due(_every(15), last, now, UTC))

    def test_ran_before_slot_is_due(self):
        now = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)
        last = datetime(2026, 6, 27, 9, 50, tzinfo=UTC)
        self.assertTrue(is_due(_every(15), last, now, UTC))

    def test_slot_older_than_catchup_window_is_lapsed(self):
        # A New Year's Day cron in June: the only matching slot is months
        # old, far outside the catch-up window — never due, even if the
        # automation has never run.
        spec = ScheduleSpec(raw="", kind=SCHEDULE_CRON, cron="0 0 1 1 *")
        now = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)
        self.assertFalse(is_due(spec, None, now, UTC))


class TestParseCron(SimpleTestCase):
    def test_parses_lists_ranges_steps(self):
        minute, hour, dom, mon, dow = parse_cron("0,30 9-17 * * 1-5")
        self.assertEqual(minute, {0, 30})
        self.assertEqual(hour, set(range(9, 18)))
        self.assertEqual(dow, {1, 2, 3, 4, 5})

    def test_dow_seven_normalizes_to_sunday(self):
        dow = parse_cron("* * * * 7")[4]
        self.assertEqual(dow, {0})

    def test_rejects_bad_arity_and_fields(self):
        with self.assertRaises(CronError):
            parse_cron("* * * *")
        with self.assertRaises(CronError):
            parse_cron("61 * * * *")
        with self.assertRaises(CronError):
            parse_cron("banana * * * *")
