from typing import Any, Dict, Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block, Page
from ..repositories import BlockRepository
from ..repositories.page_repository import PageRepository


class MoveBlockToPageForm(BaseForm):
    """Inputs for moving a single block + its descendants to an arbitrary page.

    Distinct from MoveBlockToDailyForm — that one resolves the target by
    date and may auto-create a daily note. Here the caller passes an
    explicit target page UUID and we never create pages on their behalf.

    ``target_parent`` (optional) nests the moved block under an existing
    block instead of promoting it to the target page's root — the
    "move under…" flow. When only ``target_parent`` is given the target
    page is derived from it, so pickers that select a block don't need
    to know its page.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
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

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")
        if block and user and block.user != user:
            raise ValidationError("Block not found")
        return block

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
