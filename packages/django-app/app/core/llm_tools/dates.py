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
_WEEKDAY_RE = re.compile(r"^(?:(next|last|this)\s+)?([a-z]+)$")

_WEEKDAY_NAMES: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def _resolve_weekday(today: date, target_weekday: int, prefix: Optional[str]) -> date:
    """Resolve a weekday token relative to ``today``.

    Bare and ``next`` forms skip today itself; ``last`` looks backward and
    also skips today; ``this`` is the current week's occurrence and may
    land on today or in the past.
    """
    if prefix == "this":
        forward = (target_weekday - today.weekday()) % 7
        return today + timedelta(days=forward)
    if prefix == "last":
        backward = (today.weekday() - target_weekday) % 7
        if backward == 0:
            backward = 7
        return today - timedelta(days=backward)
    forward = (target_weekday - today.weekday()) % 7
    if forward == 0:
        forward = 7
    return today + timedelta(days=forward)


def parse_relative_date(value: Any, today: date) -> Optional[date]:
    """Parse a date input that accepts ISO YYYY-MM-DD or simple relative
    tokens ('today', 'tomorrow', 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw',
    weekday names, 'next <weekday>', 'last <weekday>', 'this <weekday>').

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
    weekday_match = _WEEKDAY_RE.match(text)
    if weekday_match:
        prefix, day_word = weekday_match.groups()
        target_weekday = _WEEKDAY_NAMES.get(day_word)
        if target_weekday is not None:
            return _resolve_weekday(today, target_weekday, prefix)
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            "expected ISO YYYY-MM-DD or 'today'/'tomorrow'/'yesterday'/"
            "'+Nd'/'-Nd'/'+Nw'/'-Nw'/'<weekday>'/'next <weekday>'/"
            f"'last <weekday>'/'this <weekday>', got '{value}'"
        ) from e
