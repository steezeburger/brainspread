"""Due-ness math for scheduled automations (issue #143).

The scheduler polls roughly once a minute and asks, per automation:
"has a scheduled slot passed since this automation last started?" —
:func:`is_due`. Slots are computed in the automation owner's timezone
(a ``daily 6:00`` fires at 6am *their* time), compared in UTC.

Catch-up semantics are deliberately catch-up-once: if the scheduler was
down across several slots, the automation fires a single time on the
next tick (the missed slots collapse), and misfires older than
``CATCHUP_WINDOW`` are skipped entirely. That matches what a user wants
from "move my stickies every morning" — running it three times to make
up for a weekend outage would be wrong.

Cron support is a minimal 5-field matcher (m h dom mon dow; ``*``,
lists, ranges, ``*/step``) — enough for the escape-hatch cadences the
presets can't express. Cron due-ness scans minutes backwards from
``now`` looking for the most recent matching minute inside the window,
which stays cheap because the window is bounded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Set

from .automation_spec import (
    SCHEDULE_CRON,
    SCHEDULE_DAILY,
    SCHEDULE_EVERY,
    SCHEDULE_HOURLY,
    SCHEDULE_WEEKLY,
    ScheduleSpec,
)

# How far back a slot can be and still fire on the next tick. Just over a
# week so a `weekly` slot missed during a weekend outage still runs, while
# anything older is treated as lapsed rather than replayed.
CATCHUP_WINDOW = timedelta(days=8)


def is_due(
    schedule: ScheduleSpec,
    last_started_at: Optional[datetime],
    now: datetime,
    tz,
) -> bool:
    """True when a slot of ``schedule`` has passed since ``last_started_at``.

    ``now`` and ``last_started_at`` are aware UTC datetimes; ``tz`` is the
    automation owner's timezone (slots for daily/weekly cadences are local
    times). A never-run automation is due once its most recent slot is
    inside the catch-up window.
    """
    slot = previous_slot(schedule, now, tz)
    if slot is None:
        return False
    if now - slot > CATCHUP_WINDOW:
        return False
    return last_started_at is None or last_started_at < slot


def previous_slot(schedule: ScheduleSpec, now: datetime, tz) -> Optional[datetime]:
    """The most recent scheduled slot at or before ``now`` (aware UTC),
    or None when no slot exists in the searchable past."""
    if schedule.kind == SCHEDULE_EVERY:
        interval = (schedule.interval_minutes or 1) * 60
        epoch = int(now.timestamp())
        return datetime.fromtimestamp(epoch - (epoch % interval), tz=now.tzinfo)

    if schedule.kind == SCHEDULE_HOURLY:
        return now.replace(minute=0, second=0, microsecond=0)

    local_now = now.astimezone(tz)

    if schedule.kind == SCHEDULE_DAILY:
        slot = local_now.replace(
            hour=schedule.hour or 0,
            minute=schedule.minute or 0,
            second=0,
            microsecond=0,
        )
        if slot > local_now:
            slot -= timedelta(days=1)
        return slot.astimezone(now.tzinfo)

    if schedule.kind == SCHEDULE_WEEKLY:
        slot = local_now.replace(
            hour=schedule.hour or 0,
            minute=schedule.minute or 0,
            second=0,
            microsecond=0,
        )
        days_back = (local_now.weekday() - (schedule.weekday or 0)) % 7
        slot -= timedelta(days=days_back)
        if slot > local_now:
            slot -= timedelta(days=7)
        return slot.astimezone(now.tzinfo)

    if schedule.kind == SCHEDULE_CRON:
        return _previous_cron_slot(schedule.cron or "", now, tz)

    return None


# ---------------------------------------------------------------------------
# Minimal cron (m h dom mon dow)
# ---------------------------------------------------------------------------

# Scanning cap for the backwards minute walk. CATCHUP_WINDOW bounds what
# is actually fireable, so scanning past it is pointless.
_MAX_CRON_SCAN_MINUTES = int(CATCHUP_WINDOW.total_seconds() // 60)

_FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


class CronError(ValueError):
    """A cron expression the matcher can't parse."""


def _parse_cron_field(field: str, lo: int, hi: int) -> Set[int]:
    values: Set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"bad step in cron field: {field!r}")
            step = int(step_s)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"bad range in cron field: {field!r}")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise CronError(f"bad cron field: {field!r}")
        if start < lo or end > hi or start > end:
            raise CronError(f"cron field out of range: {field!r}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> List[Set[int]]:
    """Parse a 5-field cron expression into per-field value sets.
    Raises ``CronError`` on malformed input. dow: 0 = Sunday (classic
    cron), 7 normalized to 0."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(f"expected 5 cron fields, got {len(fields)}")
    parsed = [
        _parse_cron_field(f, lo, hi) for f, (lo, hi) in zip(fields, _FIELD_RANGES)
    ]
    if 7 in parsed[4]:
        parsed[4].discard(7)
        parsed[4].add(0)
    return parsed


def _cron_matches(parsed: List[Set[int]], local: datetime) -> bool:
    minute, hour, dom, mon, dow = parsed
    # Python weekday(): Mon=0..Sun=6 → cron dow Sun=0..Sat=6.
    cron_dow = (local.weekday() + 1) % 7
    return (
        local.minute in minute
        and local.hour in hour
        and local.day in dom
        and local.month in mon
        and cron_dow in dow
    )


def _previous_cron_slot(expr: str, now: datetime, tz) -> Optional[datetime]:
    try:
        parsed = parse_cron(expr)
    except CronError:
        return None
    local = now.astimezone(tz).replace(second=0, microsecond=0)
    for _ in range(_MAX_CRON_SCAN_MINUTES):
        if _cron_matches(parsed, local):
            return local.astimezone(now.tzinfo)
        local -= timedelta(minutes=1)
    return None
