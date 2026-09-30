from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Block, BlockRevision
from ..repositories import BlockRepository


class ToggleBlockTodoForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block = UUIDModelChoiceField(queryset=BlockRepository.get_queryset(), required=True)
    # The block_type the client believes the block is currently in (its
    # last-seen state). Optional and opt-in — omitting it (existing MCP /
    # AI-chat callers) skips the check below entirely, cycling from
    # whatever the server's actual state is, same as before.
    expected_from_type = forms.ChoiceField(
        choices=Block._meta.get_field("block_type").choices, required=False
    )
    # Who's making this change, for BlockRevision attribution. Omitted by
    # the web UI (the command defaults to "user"); the MCP tools pass
    # their own value explicitly.
    source = forms.ChoiceField(choices=BlockRevision.SOURCE_CHOICES, required=False)

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
