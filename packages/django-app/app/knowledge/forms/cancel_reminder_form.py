from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import ReminderRepository


class CancelReminderForm(BaseForm):
    """Inputs for the assistant's cancel_reminder tool.

    Cancels a pending reminder without clearing the block's
    scheduled_for. Refuses to cancel reminders that have already fired
    (sent / failed / etc).
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    reminder = UUIDModelChoiceField(
        queryset=ReminderRepository.get_queryset(), required=True
    )

    def clean_reminder(self):
        reminder = self.cleaned_data.get("reminder")
        user = self.cleaned_data.get("user")
        if reminder and user and reminder.block.user_id != user.id:
            raise ValidationError("Reminder not found")
        return reminder
