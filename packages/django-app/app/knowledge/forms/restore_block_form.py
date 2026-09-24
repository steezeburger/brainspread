from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block
from ..repositories import BlockRepository


class RestoreBlockForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(
        queryset=BlockRepository.get_deleted_queryset(), required=True
    )

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")

        if block and user and block.user != user:
            raise ValidationError("Block not found")

        # A block whose page is still archived would come back "active"
        # but unreachable — PageRepository excludes archived pages, so
        # there'd be nowhere to render it. Restoring the page cascades
        # every block on it, which is a bigger action than restoring one
        # block should trigger implicitly, so require it explicitly first.
        if block and not block.page.is_active:
            raise ValidationError(
                "This block's page is also in Trash — restore the page first."
            )

        return block

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
