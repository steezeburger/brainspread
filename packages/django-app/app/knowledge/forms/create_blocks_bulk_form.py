from typing import Any, Dict, List

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import BlockRepository, PageRepository

VALID_BLOCK_TYPES = (
    "bullet",
    "todo",
    "doing",
    "done",
    "later",
    "wontdo",
    "heading",
    "code",
    "quote",
)


class CreateBlocksBulkForm(BaseForm):
    """Inputs for create_blocks_bulk — make N blocks under one parent
    or page in a single approval.

    Either `parent_uuid` (becomes children of that block) or
    `page_uuid` (becomes root-level blocks on that page) must be
    supplied. `blocks` is a list of {content, block_type?, order?}.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=False)
    parent = UUIDModelChoiceField(
        queryset=BlockRepository.get_queryset(), required=False
    )
    blocks = forms.JSONField()

    def clean(self):
        cleaned = super().clean()
        page = cleaned.get("page")
        parent = cleaned.get("parent")
        if page is None and parent is None:
            raise ValidationError("either page or parent must be provided")
        if parent is not None and page is None:
            cleaned["page"] = parent.page
        if page is not None and parent is not None and parent.page_id != page.id:
            raise ValidationError("parent block belongs to a different page")
        return cleaned

    def clean_blocks(self) -> List[Dict[str, Any]]:
        raw = self.cleaned_data.get("blocks")
        if not isinstance(raw, list) or not raw:
            raise ValidationError("blocks must be a non-empty list")
        if len(raw) > 50:
            raise ValidationError(f"too many blocks ({len(raw)}); max 50")
        cleaned: List[Dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValidationError(f"blocks[{i}] must be an object")
            content = (item.get("content") or "").strip()
            if not content:
                raise ValidationError(f"blocks[{i}].content is required")
            block_type = (item.get("block_type") or "bullet").strip().lower()
            if block_type not in VALID_BLOCK_TYPES:
                raise ValidationError(
                    f"blocks[{i}].block_type '{block_type}' is invalid"
                )
            entry: Dict[str, Any] = {
                "content": content,
                "block_type": block_type,
            }
            if "order" in item and item["order"] is not None:
                try:
                    entry["order"] = int(item["order"])
                except (TypeError, ValueError):
                    raise ValidationError(f"blocks[{i}].order must be an integer")
            cleaned.append(entry)
        return cleaned
