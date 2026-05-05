import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class BulkScheduleForm(BaseForm):
    """Inputs for the assistant's bulk_schedule tool — set the same
    scheduled_for on N blocks, optionally creating / replacing pending
    reminders on each.

    Two modes, picked by whether `reminder_time` is supplied:

    - reminder_time absent: dates move; existing pending reminders
      shift by each block's per-block delta to preserve time-of-day.
      Blocks without a previous date just get the new date set, no
      reminder is created.

    - reminder_time present: each block routes through
      ScheduleBlockCommand, which replaces any existing pending
      reminder with a new one at `reminder_date` + `reminder_time`
      (reminder_date defaults to new_date when omitted). Matches
      single schedule_block's semantics, batched.

    Date and time are pre-resolved by the executor (which accepts
    LLM-friendly tokens like 'today' / '+7d' for dates and
    '+Nm' / '+Nh' for times) before the form sees them.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    new_date = forms.DateField()
    # Mirrors ScheduleBlockForm — both optional. reminder_date defaults
    # to new_date in the command when reminder_time is set but
    # reminder_date isn't.
    reminder_date = forms.DateField(required=False)
    reminder_time = forms.TimeField(required=False)

    def clean_block_uuids(self) -> List[str]:
        raw = self.cleaned_data.get("block_uuids")
        if not isinstance(raw, list) or not raw:
            raise ValidationError("block_uuids must be a non-empty list")
        normalized: List[str] = []
        seen: set[str] = set()
        for i, item in enumerate(raw):
            try:
                parsed = uuid_lib.UUID(str(item))
            except (ValueError, AttributeError, TypeError):
                raise ValidationError(
                    f"item at index {i} has an invalid UUID: {item!r}"
                )
            s = str(parsed)
            if s in seen:
                continue
            seen.add(s)
            normalized.append(s)
        return normalized
