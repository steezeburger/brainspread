import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class BulkCancelRemindersForm(BaseForm):
    """Inputs for the assistant's bulk_cancel_reminders tool.

    Cancels the pending reminder on each block in the list (each block
    has at most one pending reminder per ScheduleBlockCommand
    semantics). Blocks without a pending reminder are reported in the
    no-op list, not as failures.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()

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
