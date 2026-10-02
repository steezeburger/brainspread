from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block, BlockRevision
from ..repositories import BlockRepository, BlockRevisionRepository


class RestoreBlockRevisionForm(BaseForm):
    """Inputs for restoring a block to a past revision's field values."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    revision = UUIDModelChoiceField(
        queryset=BlockRevisionRepository.get_queryset(), required=True
    )
    # Who's restoring — defaults to "user" (the only surface today is the
    # block history modal's restore button).
    source = forms.ChoiceField(choices=BlockRevision.SOURCE_CHOICES, required=False)

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")

        if block and user and block.user != user:
            raise ValidationError("Block not found")

        return block

    def clean_revision(self) -> BlockRevision:
        revision = self.cleaned_data.get("revision")
        block = self.cleaned_data.get("block")

        if revision and block and revision.block_id != block.id:
            raise ValidationError("Revision not found")

        return revision

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
