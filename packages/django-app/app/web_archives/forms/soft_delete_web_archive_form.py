from django import forms
from django.core.exceptions import ValidationError

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository
from knowledge.models import Block
from knowledge.repositories import BlockRepository


class SoftDeleteWebArchiveForm(BaseForm):
    """
    Soft-delete the archive tied to a block. Used by DeleteBlockCommand
    as an explicit cleanup step before the block itself is removed, so
    the archive row + its stored bytes survive for a future library /
    restore view.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset())

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")
        if block and user and block.user != user:
            raise ValidationError("Block not found")
        return block

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
