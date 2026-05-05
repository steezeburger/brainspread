import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class BulkClearScheduleForm(BaseForm):
    """Inputs for the assistant's bulk_clear_schedule tool.

    Mirrors the single clear_schedule shape (drop scheduled_for AND
    cancel any pending reminder) but applies it to many blocks in one
    approval.
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
