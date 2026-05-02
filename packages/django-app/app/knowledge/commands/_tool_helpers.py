"""Shared helpers for the assistant-tool commands.

These commands return JSON-serializable dicts that ride on the chat
tool_result wire format, so they share a few formatting helpers (block
summaries, timezone resolution).
"""

from typing import Any, Dict

import pytz

from core.models import User


def summarize_block(block) -> Dict[str, Any]:
    """Compact block summary for list_* tools — small enough to keep many
    in a tool result, rich enough for the chat surface to render."""
    return {
        "block_uuid": str(block.uuid),
        "content": block.content,
        "block_type": block.block_type,
        "scheduled_for": (
            block.scheduled_for.isoformat() if block.scheduled_for else None
        ),
        "completed_at": (
            block.completed_at.isoformat() if block.completed_at else None
        ),
        "page_uuid": str(block.page.uuid) if block.page else None,
        "page_title": block.page.title if block.page else None,
        "page_slug": block.page.slug if block.page else None,
        "pending_reminder_date": block._pending_reminder_local_date(),
        "pending_reminder_time": block._pending_reminder_local_time(),
    }


def user_tz(user: User):
    """Resolve the user's pytz timezone, falling back to UTC."""
    try:
        return pytz.timezone(user.timezone or "UTC")
    except pytz.UnknownTimeZoneError:
        return pytz.UTC
