import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class BulkSnoozeForm(BaseForm):
    """Inputs for the assistant's bulk_snooze tool.

    Push N blocks' schedules + pending reminders forward by the same
    `days` and/or `hours`. Same semantics as single snooze_block, just
    batched.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    days = forms.IntegerField(min_value=-365, max_value=365, required=False, initial=0)
    hours = forms.IntegerField(min_value=-72, max_value=72, required=False, initial=0)

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

    def clean(self):
        cleaned = super().clean()
        days = cleaned.get("days") or 0
        hours = cleaned.get("hours") or 0
        if days == 0 and hours == 0:
            raise ValidationError("at least one of days or hours must be non-zero")
        cleaned["days"] = days
        cleaned["hours"] = hours
        return cleaned
