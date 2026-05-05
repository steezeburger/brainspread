import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class BulkRescheduleForm(BaseForm):
    """Inputs for the assistant's bulk_reschedule tool — set the same
    scheduled_for on many blocks. Pending reminders attached to those
    blocks shift by the per-block delta so a 'next Monday' move keeps
    the reminder time-of-day intact.

    Date is pre-resolved to ISO YYYY-MM-DD by the executor (which
    accepts 'today' / '+7d' style tokens) before the form sees it.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    new_date = forms.DateField()

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
