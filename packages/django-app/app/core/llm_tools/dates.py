"""Parse LLM-friendly relative date tokens.

Tools that take date args end up needing the same fuzzy parser: the
model often produces ``"today"`` / ``"tomorrow"`` / ``"+7d"`` / ``"-2w"``
rather than a strict ISO string. Keeping the parser here lets every
tool registry (ai_chat, mcp_server) share one implementation that's
unit-tested in one place.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

_RELATIVE_OFFSET_RE = re.compile(r"^([+-])(\d+)([dw])$")

# Monday-first, matching date.weekday(). Three-letter abbreviations are
# accepted alongside the full names because that's what the automation
# schedule cadence (`weekly fri 17:30`) already uses.
_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_WEEKDAY_QUALIFIERS = ("next", "last", "this")


def _parse_weekday(text: str, today: date) -> Optional[date]:
    """Resolve a weekday token to a date, or None if it isn't one.

    Bare and ``next`` forms both mean "the next occurrence, skipping
    today" — asking for ``monday`` on a Monday gives you *next* Monday.
    That's what makes a token like ``move_to_daily "next monday"``
    stable: the target is a real Monday no matter which day the
    automation actually runs on, where ``+3d`` silently drifts. ``last``
    is the mirror (most recent past occurrence, also skipping today),
    and ``this`` is the current Monday-anchored week's occurrence, which
    may be in the past.
    """
    words = text.split()
    if len(words) == 1:
        qualifier, name = None, words[0]
    elif len(words) == 2 and words[0] in _WEEKDAY_QUALIFIERS:
        qualifier, name = words
    else:
        return None

    target = _WEEKDAYS.get(name)
    if target is None:
        return None

    if qualifier == "last":
        # `or 7` skips today, mirroring the forward case below.
        return today - timedelta(days=((today.weekday() - target) % 7) or 7)
    if qualifier == "this":
        # Monday-anchored: walk back to this week's Monday, then forward.
        return today - timedelta(days=today.weekday()) + timedelta(days=target)
    return today + timedelta(days=((target - today.weekday()) % 7) or 7)


def parse_relative_date(value: Any, today: date) -> Optional[date]:
    """Parse a date input that accepts ISO YYYY-MM-DD or simple relative
    tokens ('today', 'tomorrow', 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw',
    and weekday names: 'monday', 'next monday', 'last monday',
    'this monday').

    Returns None when the input is empty / missing. Raises ValueError on
    unrecognised formats so the caller can surface a helpful error.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text == "yesterday":
        return today - timedelta(days=1)
    match = _RELATIVE_OFFSET_RE.match(text)
    if match:
        sign, num, unit = match.groups()
        amount = int(num) * (1 if sign == "+" else -1)
        days = amount if unit == "d" else amount * 7
        return today + timedelta(days=days)
    weekday = _parse_weekday(text, today)
    if weekday is not None:
        return weekday
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            "expected ISO YYYY-MM-DD, 'today'/'tomorrow'/'yesterday', "
            "'+Nd'/'-Nd'/'+Nw'/'-Nw', or a weekday like 'monday' / "
            f"'next monday' / 'last monday' / 'this monday', got '{value}'"
        ) from e
