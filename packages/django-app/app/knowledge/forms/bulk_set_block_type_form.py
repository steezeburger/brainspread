import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository

VALID_BLOCK_TYPES = (
    "bullet",
    "todo",
    "doing",
    "done",
    "later",
    "wontdo",
    "heading",
    "quote",
    "code",
    "divider",
)


class BulkSetBlockTypeForm(BaseForm):
    """Inputs for bulk_set_block_type — set N blocks to the same type."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    new_type = forms.CharField()

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

    def clean_new_type(self) -> str:
        new_type = (self.cleaned_data.get("new_type") or "").strip().lower()
        if new_type not in VALID_BLOCK_TYPES:
            raise ValidationError(
                f"invalid block_type '{new_type}'; must be one of "
                f"{', '.join(VALID_BLOCK_TYPES)}"
            )
        return new_type
