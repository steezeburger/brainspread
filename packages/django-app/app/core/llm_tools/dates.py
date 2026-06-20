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


def parse_relative_date(value: Any, today: date) -> Optional[date]:
    """Parse a date input that accepts ISO YYYY-MM-DD or simple relative
    tokens ('today', 'tomorrow', 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw').

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
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            f"expected ISO YYYY-MM-DD or 'today'/'tomorrow'/'+Nd', got '{value}'"
        ) from e
