from typing import Dict, List, Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm
from core.models import User
from core.repositories import UserRepository

from .models import AIModel, ChatSession, PendingToolApproval
from .repositories import UserSettingsRepository


class SendMessageForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    message = forms.CharField(
        required=False
    )  # We'll handle validation in clean_message
    model = forms.CharField(required=True)  # Model selection per request
    session_id = forms.CharField(required=False)
    context_blocks = forms.JSONField(required=False)
    enable_notes_tools = forms.BooleanField(required=False)
    # Independent of enable_notes_tools so users can grant reads without
    # writes (or writes without reads, though the model rarely needs that).
    enable_notes_write_tools = forms.BooleanField(required=False)
    # NullBooleanField so we can distinguish "omitted" (legacy clients that
    # never send this flag expect web search on) from an explicit false.
    enable_web_search = forms.NullBooleanField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_message(self) -> str:
        message = self.cleaned_data.get("message")
        if not message or not message.strip():
            raise ValidationError("Message cannot be empty")
        return message.strip()

    def clean_session_id(self) -> Optional[ChatSession]:
        session_id = self.cleaned_data.get("session_id")
        user = self.cleaned_data.get("user")
        if session_id and user:
            try:
                session = ChatSession.objects.get(uuid=session_id, user=user)
                return session
            except ChatSession.DoesNotExist:
                # Return None for non-existent sessions - let the command create a new one
                return None
        return None

    def clean_enable_web_search(self) -> bool:
        value = self.cleaned_data.get("enable_web_search")
        return True if value is None else bool(value)

    def clean_context_blocks(self) -> List[Dict]:
        context_blocks = self.cleaned_data.get("context_blocks")
        if context_blocks is None:
            return []

        if not isinstance(context_blocks, list):
            raise ValidationError("Context blocks must be a list")

        return context_blocks

    def clean(self):
        cleaned_data = super().clean()

        user = cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")

        # Get model and validate it exists in our database
        model_name = cleaned_data.get("model")
        if not model_name:
            raise ValidationError("Model is required.")

        # Look up the model in our database
        try:
            ai_model = AIModel.objects.select_related("provider").get(
                name=model_name, is_active=True
            )
        except AIModel.DoesNotExist:
            raise ValidationError(
                f"Model '{model_name}' is not available or not found."
            )

        # Get the provider and check API key
        provider = ai_model.provider
        provider_name = provider.name.lower()

        # Check API key for the provider
        user_settings_repo = UserSettingsRepository()
        api_key = user_settings_repo.get_api_key(user, provider)
        if not api_key:
            raise ValidationError(
                f"No API key configured for {provider.name}. Please add your API key in settings."
            )

        # Add validated data to cleaned_data
        cleaned_data["ai_model"] = ai_model
        cleaned_data["provider"] = provider
        cleaned_data["provider_name"] = provider_name
        cleaned_data["api_key"] = api_key

        return cleaned_data


class ResumeApprovalForm(BaseForm):
    """Validate a resume payload for a PendingToolApproval.

    Input:
      - user: the requesting user (set server-side).
      - approval_id: uuid of the paused approval.
      - decisions: {tool_use_id: "approve"|"reject"} covering every write
        tool in the pending approval. Read-only tools are auto-approved.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    approval_id = forms.CharField(required=True)
    decisions = forms.JSONField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_decisions(self) -> Dict[str, str]:
        raw = self.cleaned_data.get("decisions") or {}
        if not isinstance(raw, dict):
            raise ValidationError("decisions must be an object")
        cleaned: Dict[str, str] = {}
        for key, value in raw.items():
            if value not in ("approve", "reject"):
                raise ValidationError(
                    f"Invalid decision '{value}' for tool {key}; expected"
                    " 'approve' or 'reject'"
                )
            cleaned[str(key)] = value
        return cleaned

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get("user")
        approval_id = cleaned_data.get("approval_id")
        decisions = cleaned_data.get("decisions") or {}

        if not approval_id or not user:
            return cleaned_data

        try:
            approval = PendingToolApproval.objects.select_related(
                "session", "ai_model", "ai_model__provider"
            ).get(uuid=approval_id)
        except PendingToolApproval.DoesNotExist:
            raise ValidationError("Pending approval not found")

        if approval.session.user_id != user.id:
            raise ValidationError("Pending approval not found")

        write_tool_use_ids = [
            tu.get("tool_use_id")
            for tu in (approval.tool_uses or [])
            if tu.get("requires_approval")
        ]
        missing = [tu_id for tu_id in write_tool_use_ids if tu_id not in decisions]
        if missing:
            raise ValidationError(
                "Missing decision for tool_use_id(s): " + ", ".join(missing)
            )

        cleaned_data["approval"] = approval
        return cleaned_data
