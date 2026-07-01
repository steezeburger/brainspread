from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import AutomationRun, Block
from ..repositories import BlockRepository


class RunAutomationForm(BaseForm):
    """Inputs for executing one automation: the acting user, the
    ``#automation`` block that defines it, and what triggered the run."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    automation_block = UUIDModelChoiceField(
        queryset=BlockRepository.get_queryset(), required=True
    )
    trigger = forms.ChoiceField(
        choices=AutomationRun.TRIGGER_CHOICES,
        required=False,
    )

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_automation_block(self) -> Block:
        block = self.cleaned_data.get("automation_block")
        user = self.cleaned_data.get("user")
        if block and user and block.user != user:
            raise ValidationError("Automation not found")
        return block

    def clean_trigger(self) -> str:
        return self.cleaned_data.get("trigger") or AutomationRun.TRIGGER_MANUAL
