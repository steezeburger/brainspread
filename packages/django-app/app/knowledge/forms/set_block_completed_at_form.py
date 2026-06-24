from django import forms
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block
from ..repositories import BlockRepository

# Terminal states whose completion time is meaningful to edit. Mirrors
# COMPLETED_TYPES in set_block_type_command; kept local to avoid a
# forms -> commands import cycle.
TERMINAL_BLOCK_TYPES = {"done", "wontdo"}


class SetBlockCompletedAtForm(BaseForm):
    """Override a completed block's completed_at timestamp.

    Used to correct the recorded completion time — e.g. a block carried
    over for days before it was finally marked done, leaving completed_at
    stamped at "mark done" time rather than when the work actually wrapped.

    Only blocks in a terminal state (done / wontdo) carry a completed_at,
    so editing is rejected for any other block_type. Clearing the value is
    intentionally not supported here — that happens automatically when a
    block transitions out of a terminal state (see SetBlockTypeCommand).

    `completed_at` accepts an ISO-8601 datetime. A trailing offset / Z is
    honored; a naive value is interpreted in the user's timezone by the
    command.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    completed_at = forms.CharField(required=True)

    def clean_block(self) -> Block:
        block = self.cleaned_data.get("block")
        user = self.cleaned_data.get("user")

        if block and user and block.user != user:
            raise ValidationError("Block not found")
        if block and block.block_type not in TERMINAL_BLOCK_TYPES:
            raise ValidationError(
                "completed_at can only be set on a done or wontdo block"
            )
        return block

    def clean_completed_at(self):
        raw = (self.cleaned_data.get("completed_at") or "").strip()
        parsed = parse_datetime(raw)
        if parsed is None:
            raise ValidationError("completed_at must be an ISO-8601 datetime")
        return parsed

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
