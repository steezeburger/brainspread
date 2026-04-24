from django import forms
from django.core.exceptions import ValidationError

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository
from knowledge.models import Block
from knowledge.repositories import BlockRepository


class GetWebArchiveForm(BaseForm):
    """
    Fetch a web archive by its anchor block UUID. Used by the frontend to
    poll for capture completion after CaptureWebArchive kicks off.
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
