"""Helpers for the block due date/time (``Block.due_at`` + ``due_at_has_time``).

A due value is all-day by default ("due that day") and stored as user-local
midnight; setting a time of day flips ``due_at_has_time`` on. These helpers
centralize the timezone-aware conversions so every command (schedule, bulk
schedule, snooze) treats all-day vs timed dues consistently.
"""

from datetime import date as date_cls
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

import pytz


def _resolve_tz(tz_name: str):
    try:
        return pytz.timezone(tz_name or "UTC")
    except pytz.UnknownTimeZoneError:
        return pytz.UTC


def combine_local_to_utc(d: date_cls, t: time, tz_name: str) -> datetime:
    """Combine a user-local date + time into a UTC-aware datetime.

    pytz needs ``localize()`` (not ``tzinfo=``) to pick the right DST offset
    for the wall-clock time.
    """
    tz = _resolve_tz(tz_name)
    return tz.localize(datetime.combine(d, t)).astimezone(pytz.UTC)


def build_due_at(
    due_date: Optional[date_cls],
    due_time: Optional[time],
    tz_name: str,
) -> Tuple[Optional[datetime], bool]:
    """Resolve a due date (+ optional time) into ``(due_at, due_at_has_time)``.

    ``due_date`` None → no due (``(None, False)``). No time → all-day, pinned
    to user-local midnight so it reads back on the right calendar date.
    """
    if due_date is None:
        return (None, False)
    has_time = due_time is not None
    due_at = combine_local_to_utc(due_date, due_time if has_time else time.min, tz_name)
    return (due_at, has_time)


def shift_due_days(
    due_at: datetime, has_time: bool, days: int, tz_name: str
) -> datetime:
    """Shift ``due_at`` by ``days`` in the user's local calendar, preserving
    the local time-of-day (or midnight for all-day items) across DST."""
    tz = _resolve_tz(tz_name)
    local = due_at.astimezone(tz)
    new_date = local.date() + timedelta(days=days)
    local_time = local.time() if has_time else time.min
    return combine_local_to_utc(new_date, local_time, tz_name)
