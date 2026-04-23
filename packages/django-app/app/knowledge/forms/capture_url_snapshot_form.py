from django import forms
from django.core.exceptions import ValidationError

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Block
from ..repositories import BlockRepository


class CaptureUrlSnapshotForm(BaseForm):
    """
    Capture a webpage snapshot for an existing block.

    The block is the anchor - callers create the embed block first (through
    the normal CreateBlock flow) then kick off capture. That keeps the block
    on screen immediately and lets snapshot state load in asynchronously.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset())
    url = forms.URLField(max_length=2048)

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
