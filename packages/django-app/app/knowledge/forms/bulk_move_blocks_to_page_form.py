import uuid as uuid_lib
from typing import Any, Dict, List, Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block, Page
from ..repositories import BlockRepository
from ..repositories.page_repository import PageRepository


class BulkMoveBlocksToPageForm(BaseForm):
    """Inputs for moving a list of blocks to an arbitrary target page.

    Sibling of BulkMoveBlocksForm — same `blocks` validation rules,
    but the target is an explicit Page UUID instead of a date. We
    never auto-create pages on this path; the caller picks an
    existing one via the page-picker modal.

    ``target_parent`` (optional) nests the moved blocks under an
    existing block instead of the target page's root — the bulk
    "move under…" flow. When only ``target_parent`` is given the
    target page is derived from it.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    blocks = forms.JSONField()
    target_page = UUIDModelChoiceField(
        queryset=PageRepository.get_queryset(), required=False
    )
    target_parent = UUIDModelChoiceField(
        queryset=BlockRepository.get_queryset(), required=False
    )

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_blocks(self) -> List[str]:
        raw = self.cleaned_data.get("blocks")

        if not isinstance(raw, list):
            raise ValidationError("blocks must be a list")
        if not raw:
            raise ValidationError("blocks list must not be empty")

        normalized: List[str] = []
        seen = set()
        for i, item in enumerate(raw):
            try:
                parsed = uuid_lib.UUID(str(item))
            except (ValueError, AttributeError, TypeError):
                raise ValidationError(
                    f"Item at index {i} has an invalid UUID: {item!r}"
                )
            s = str(parsed)
            if s in seen:
                continue
            seen.add(s)
            normalized.append(s)

        return normalized

    def clean_target_page(self) -> Optional[Page]:
        page = self.cleaned_data.get("target_page")
        user = self.cleaned_data.get("user")
        if page and user and page.user != user:
            raise ValidationError("Target page not found")
        return page

    def clean_target_parent(self) -> Optional[Block]:
        parent = self.cleaned_data.get("target_parent")
        user = self.cleaned_data.get("user")
        if parent and user and parent.user != user:
            raise ValidationError("Target parent not found")
        return parent

    def clean(self) -> Dict[str, Any]:
        cleaned_data = super().clean()
        target_page = cleaned_data.get("target_page")
        target_parent = cleaned_data.get("target_parent")

        if not target_page and not target_parent:
            raise ValidationError("target_page or target_parent is required")

        if target_parent:
            if target_page and target_parent.page_id != target_page.pk:
                raise ValidationError("target_parent does not belong to target_page")
            cleaned_data["target_page"] = target_parent.page

        return cleaned_data
