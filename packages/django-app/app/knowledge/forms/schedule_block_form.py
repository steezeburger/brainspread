from datetime import date, time
from typing import List, Optional, Tuple

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block
from ..repositories import BlockRepository

MAX_REMINDERS_PER_BLOCK = 10


class ScheduleBlockForm(BaseForm):
    """Set (or clear) a block's due date/time, optionally with reminders
    at chosen user-local times.

    Behavior:
    - `due_date` empty (or absent) clears the block's due date.
    - `due_time` is optional; absent = all-day ("due that day"), present =
      due at that specific time of day.
    - `reminders` is a list of ``{"date": "YYYY-MM-DD"?, "time": "HH:MM"}``;
      an entry without a date falls back to `due_date` in the command.
    - `reminder_date` / `reminder_time` are the single-reminder legacy of
      the same, kept for the MCP / AI tools; ignored when `reminders` is
      supplied.
    - Reminders only take effect when `due_date` is also set.
    - On every save we delete the block's pending reminders before
      recreating the submitted set — so re-scheduling doesn't stack.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    due_date = forms.DateField(required=False)
    due_time = forms.TimeField(required=False)
    # Editable reminder list from the popover. Each entry's date is the
    # concrete day the ping fires on (offset chips resolve client-side).
    reminders = forms.JSONField(required=False)
    # If reminder_date is omitted, the command falls back to due_date
    # (i.e. "remind me the day of"). Frontend offset chips (day-of / 1d
    # before / etc) compute their own absolute date and submit it here.
    reminder_date = forms.DateField(required=False)
    reminder_time = forms.TimeField(required=False)

    def clean_reminders(self) -> Optional[List[Tuple[Optional[date], time]]]:
        """Validate the reminder list into [(date|None, time), …]."""
        raw = self.cleaned_data.get("reminders")
        if raw in (None, ""):
            return None
        if not isinstance(raw, list):
            raise ValidationError("reminders must be a list")
        if len(raw) > MAX_REMINDERS_PER_BLOCK:
            raise ValidationError(
                f"at most {MAX_REMINDERS_PER_BLOCK} reminders per block"
            )
        parsed: List[Tuple[Optional[date], time]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValidationError(f"reminder {i} must be an object")
            time_field = forms.TimeField()
            try:
                t = time_field.clean(item.get("time"))
            except ValidationError:
                raise ValidationError(f"reminder {i} has an invalid time")
            d = None
            if item.get("date"):
                try:
                    d = forms.DateField().clean(item["date"])
                except ValidationError:
                    raise ValidationError(f"reminder {i} has an invalid date")
            parsed.append((d, t))
        return parsed

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")

        if block and user and block.user != user:
            raise ValidationError("Block not found")
        return block

    def clean(self) -> dict:
        # A missing due_date means "clear the schedule", so a stale client
        # still sending the pre-rename `scheduled_for` key would silently
        # wipe schedules and pending reminders. Reject it loudly instead.
        if "scheduled_for" in self.data:
            raise ValidationError(
                "scheduled_for was renamed to due_date — refusing to treat "
                "this legacy payload as a schedule clear. Reload the app."
            )
        return super().clean()

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
