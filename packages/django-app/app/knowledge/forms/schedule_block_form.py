from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block
from ..repositories import BlockRepository


class ScheduleBlockForm(BaseForm):
    """Set (or clear) a block's scheduled_for date, optionally adding a
    reminder at a chosen user-local time on that date.

    Behavior:
    - `scheduled_for` empty (or absent) clears the block's schedule.
    - `reminder_time` only takes effect when `scheduled_for` is also set.
    - On every save we delete the block's pending reminders before
      (optionally) creating the new one — so re-scheduling doesn't stack.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    scheduled_for = forms.DateField(required=False)
    # If reminder_date is omitted, the command falls back to scheduled_for
    # (i.e. "remind me the day of"). Frontend offset chips (day-of / 1d
    # before / etc) compute their own absolute date and submit it here.
    reminder_date = forms.DateField(required=False)
    reminder_time = forms.TimeField(required=False)

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
