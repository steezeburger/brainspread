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
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    target_page = UUIDModelChoiceField(
        queryset=PageRepository.get_queryset(), required=True
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

    def clean_target_page(self) -> Page:
        page = self.cleaned_data.get("target_page")
        user = self.cleaned_data.get("user")
        if page and user and page.user != user:
            raise ValidationError("Target page not found")
        return page
