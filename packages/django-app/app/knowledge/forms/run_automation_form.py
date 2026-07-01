from typing import Any, Dict

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import AutomationRun, Block
from ..repositories import BlockRepository
from ..services.automation_spec import AutomationSpecError, parse_automation_block


class RunAutomationForm(BaseForm):
    """Inputs for executing one automation: the acting user, the
    ``#automation`` block that defines it (by uuid, or by the automation's
    derived slug — the reference the LLM tools use), and what triggered
    the run."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    automation_block = UUIDModelChoiceField(
        queryset=BlockRepository.get_queryset(), required=False
    )
    automation_slug = forms.CharField(required=False)
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

    def clean(self) -> Dict[str, Any]:
        cleaned_data = super().clean()
        user = cleaned_data.get("user")
        block = cleaned_data.get("automation_block")
        slug = (cleaned_data.get("automation_slug") or "").strip()

        if block is None and slug and user is not None:
            block = self._resolve_by_slug(user, slug)
            cleaned_data["automation_block"] = block

        if cleaned_data.get("automation_block") is None:
            raise ValidationError("Pass automation_block (uuid) or automation_slug")
        return cleaned_data

    @staticmethod
    def _resolve_by_slug(user: User, slug: str) -> Block:
        """Match against each automation's derived slug (see
        ``parse_automation_block``). Malformed definitions are skipped —
        they can't produce a slug to match."""
        for candidate in BlockRepository.get_automation_blocks(user):
            try:
                spec = parse_automation_block(candidate)
            except AutomationSpecError:
                continue
            if spec.slug == slug:
                return candidate
        raise ValidationError(f"No automation with slug `{slug}`")
