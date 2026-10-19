from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ListMcpAccessTokensForm
from ..models import McpAccessToken
from ..repositories import McpAccessTokenRepository


class ListMcpAccessTokensCommand(AbstractBaseCommand):
    """The user's unrevoked MCP access tokens, newest first. Expired ones
    are included so the UI can show them as expired."""

    def __init__(self, form: ListMcpAccessTokensForm) -> None:
        self.form = form

    def execute(self) -> List[McpAccessToken]:
        super().execute()
        return list(
            McpAccessTokenRepository.list_unrevoked_for_user(
                self.form.cleaned_data["user"]
            )
        )
