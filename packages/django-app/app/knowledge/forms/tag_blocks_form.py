"""Forms for the assistant's tag_blocks / untag_blocks tools.

Both forms accept the same shape — a list of block UUIDs and a list of
page UUIDs — but live as distinct classes so each command type-checks
against its specific input.
"""

import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


def _normalize_uuid_list(raw, label: str) -> List[str]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError(f"{label} must be a non-empty list")
    normalized: List[str] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        try:
            parsed = uuid_lib.UUID(str(item))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError(f"{label}[{i}] is not a valid UUID: {item!r}")
        s = str(parsed)
        if s in seen:
            continue
        seen.add(s)
        normalized.append(s)
    return normalized


class TagBlocksForm(BaseForm):
    """Add page tags to multiple blocks (block.pages M2M)."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    page_uuids = forms.JSONField()

    def clean_block_uuids(self) -> List[str]:
        return _normalize_uuid_list(self.cleaned_data.get("block_uuids"), "block_uuids")

    def clean_page_uuids(self) -> List[str]:
        return _normalize_uuid_list(self.cleaned_data.get("page_uuids"), "page_uuids")


class UntagBlocksForm(BaseForm):
    """Remove page tags from multiple blocks (block.pages M2M)."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()
    page_uuids = forms.JSONField()

    def clean_block_uuids(self) -> List[str]:
        return _normalize_uuid_list(self.cleaned_data.get("block_uuids"), "block_uuids")

    def clean_page_uuids(self) -> List[str]:
        return _normalize_uuid_list(self.cleaned_data.get("page_uuids"), "page_uuids")
