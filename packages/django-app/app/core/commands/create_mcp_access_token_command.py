from datetime import timedelta
from typing import NamedTuple

from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import CreateMcpAccessTokenForm
from ..mcp_access_keys import (
    MCP_ACCESS_KEY_DISPLAY_LENGTH,
    generate_mcp_access_key,
    hash_mcp_access_key,
)
from ..models import McpAccessToken
from ..repositories import McpAccessTokenRepository


class CreateMcpAccessTokenResult(NamedTuple):
    token: McpAccessToken
    # Plaintext key. Only returned here; the DB keeps a hash.
    key: str


class CreateMcpAccessTokenCommand(AbstractBaseCommand):
    """Mint a named MCP access token for one machine / Claude instance."""

    def __init__(self, form: CreateMcpAccessTokenForm) -> None:
        self.form = form

    def execute(self) -> CreateMcpAccessTokenResult:
        super().execute()

        expires_in_days = self.form.cleaned_data.get("expires_in_days")
        expires_at = (
            timezone.now() + timedelta(days=expires_in_days)
            if expires_in_days
            else None
        )
        key = generate_mcp_access_key()
        token = McpAccessTokenRepository.create(
            user=self.form.cleaned_data["user"],
            name=self.form.cleaned_data["name"],
            key_prefix=key[:MCP_ACCESS_KEY_DISPLAY_LENGTH],
            key_hash=hash_mcp_access_key(key),
            expires_at=expires_at,
        )
        return CreateMcpAccessTokenResult(token=token, key=key)
