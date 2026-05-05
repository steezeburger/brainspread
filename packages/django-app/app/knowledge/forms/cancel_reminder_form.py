from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import BlockRepository


class CancelReminderForm(BaseForm):
    """Inputs for the assistant's cancel_reminder tool.

    Identified by `block` (the block whose pending reminder should be
    killed), not by the reminder's own uuid — there's at most one
    pending reminder per block (see ScheduleBlockCommand replace-on-
    save semantics) and the block uuid is the natural identifier the
    assistant already knows. Mirrors clear_schedule's API.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)

    def clean_block(self):
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")
        if block and user and block.user_id != user.id:
            raise ValidationError("Block not found")
        return block
