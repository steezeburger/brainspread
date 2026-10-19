from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import RevokeMcpAccessTokenForm
from ..models import McpAccessToken
from ..repositories import McpAccessTokenRepository


class RevokeMcpAccessTokenCommand(AbstractBaseCommand):
    """Revoke one MCP access token. Takes effect on the client's next call."""

    def __init__(self, form: RevokeMcpAccessTokenForm) -> None:
        self.form = form

    def execute(self) -> McpAccessToken:
        super().execute()

        token = McpAccessTokenRepository.get_unrevoked_by_uuid(
            str(self.form.cleaned_data["token_uuid"]),
            user=self.form.cleaned_data["user"],
        )
        if token is None:
            raise ValidationError("Token not found")
        return McpAccessTokenRepository.revoke(token)
