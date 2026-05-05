from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import BlockRepository


class SnoozeBlockForm(BaseForm):
    """Inputs for the assistant's snooze_block tool.

    Push a single block's schedule (and any pending reminder) forward by
    `days` and/or `hours`. At least one of the two must be non-zero.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    days = forms.IntegerField(min_value=-365, max_value=365, required=False, initial=0)
    hours = forms.IntegerField(min_value=-72, max_value=72, required=False, initial=0)

    def clean_block(self):
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")
        if block and user and block.user_id != user.id:
            raise ValidationError("Block not found")
        return block

    def clean(self):
        cleaned = super().clean()
        days = cleaned.get("days") or 0
        hours = cleaned.get("hours") or 0
        if days == 0 and hours == 0:
            raise ValidationError("at least one of days or hours must be non-zero")
        cleaned["days"] = days
        cleaned["hours"] = hours
        return cleaned
