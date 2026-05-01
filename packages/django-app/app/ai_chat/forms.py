from typing import Dict, List, Optional

from django import forms
from django.core.exceptions import ValidationError

from assets.models import Asset
from assets.repositories import AssetRepository
from common.forms import BaseForm
from core.models import User
from core.repositories import UserRepository

from .models import AIModel, ChatSession, PendingToolApproval
from .repositories import UserSettingsRepository

# Cap how many images a single chat turn can send to the model. Each image
# costs real tokens (Anthropic ~1.6k for a 1024px image) and providers
# enforce their own per-request limits, so 5 keeps round-trips predictable.
MAX_ATTACHMENTS_PER_MESSAGE = 5


class SendMessageForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    message = forms.CharField(
        required=False
    )  # We'll handle validation in clean_message
    model = forms.CharField(required=True)  # Model selection per request
    session_id = forms.CharField(required=False)
    context_blocks = forms.JSONField(required=False)
    # Asset uuids to attach to this turn. Validated as a list of strings;
    # ownership + image-only check happens in clean_asset_uuids.
    asset_uuids = forms.JSONField(required=False)
    enable_notes_tools = forms.BooleanField(required=False)
    # Independent of enable_notes_tools so users can grant reads without
    # writes (or writes without reads, though the model rarely needs that).
    enable_notes_write_tools = forms.BooleanField(required=False)
    # Skip the per-call approval gate for write tools. Opt-in per request;
    # callers should surface a visible warning when this is on.
    auto_approve_notes_writes = forms.BooleanField(required=False)
    # NullBooleanField so we can distinguish "omitted" (legacy clients that
    # never send this flag expect web search on) from an explicit false.
    enable_web_search = forms.NullBooleanField(required=False)
    # Opt-in JSON-schema structured output. When set, the assistant text is
    # constrained to JSON validating the supplied schema. Each provider has
    # its own wire shape; services translate from the unified dict below.
    response_format = forms.JSONField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_message(self) -> str:
        # The empty-vs-image check happens in clean() below - by the time
        # field-level clean_message runs, asset_uuids hasn't been
        # processed yet (Django runs clean_<field> in declaration
        # order), so we can't decide here whether an empty caption is OK.
        return (self.cleaned_data.get("message") or "").strip()

    def clean_asset_uuids(self) -> List[Asset]:
        raw = self.cleaned_data.get("asset_uuids") or []
        if not raw:
            return []
        if not isinstance(raw, list):
            raise ValidationError("asset_uuids must be a list")
        if len(raw) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ValidationError(
                f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message"
            )

        user = self.cleaned_data.get("user")
        if user is None:
            # clean_user already raised if user was missing; bail out
            # gracefully here rather than dereferencing None.
            return []

        resolved: List[Asset] = []
        for uuid in raw:
            asset = AssetRepository.get_by_uuid(uuid=str(uuid), user=user)
            if asset is None:
                raise ValidationError(f"Asset {uuid} not found")
            # Hard-cap to images for v1. Other file_types (PDF, video, audio)
            # are intentional follow-ups - each provider has its own
            # constraints (e.g. Anthropic accepts PDFs as a separate block
            # type, OpenAI does not yet).
            if asset.file_type != Asset.FILE_TYPE_IMAGE:
                raise ValidationError(
                    f"Only image attachments are supported in chat for now"
                    f" (got {asset.file_type or 'unknown'})"
                )
            resolved.append(asset)
        return resolved

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

    def clean_response_format(self) -> Optional[Dict]:
        """Validate and normalize a structured-output request.

        The unified shape is:
            {
              "type": "json_schema",       # required
              "schema": {...JSON Schema},  # required, non-empty object
              "name": "string",            # optional, defaults applied
              "strict": bool               # optional (OpenAI-only)
            }
        Each service translates this to its native parameter on the wire.
        """
        value = self.cleaned_data.get("response_format")
        if value in (None, "", {}, []):
            return None
        if not isinstance(value, dict):
            raise ValidationError("response_format must be an object")
        fmt_type = value.get("type")
        if fmt_type != "json_schema":
            raise ValidationError("response_format.type must be 'json_schema'")
        schema = value.get("schema")
        if not isinstance(schema, dict) or not schema:
            raise ValidationError(
                "response_format.schema must be a non-empty JSON Schema object"
            )
        name = value.get("name")
        if name is not None and not isinstance(name, str):
            raise ValidationError("response_format.name must be a string")
        normalized: Dict = {
            "type": fmt_type,
            "schema": schema,
            "name": name or "structured_response",
        }
        if "strict" in value:
            normalized["strict"] = bool(value.get("strict"))
        return normalized

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

        # Empty caption is OK iff the user is sending images. We check
        # here (not in clean_message) because clean_<field> methods run
        # in declaration order and asset_uuids hasn't been processed yet
        # when clean_message fires.
        message = cleaned_data.get("message") or ""
        asset_uuids = cleaned_data.get("asset_uuids") or []
        if not message and not asset_uuids:
            self.add_error("message", "Message cannot be empty")

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
      - auto_approve_notes_writes: optional override of the persisted
        preference. Lets the user toggle auto-approve after a pause has
        already happened — without this, the approval row's stale value
        from the original request would win and the next pause would
        block again.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    approval_id = forms.CharField(required=True)
    decisions = forms.JSONField(required=False)
    auto_approve_notes_writes = forms.NullBooleanField(required=False)

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
