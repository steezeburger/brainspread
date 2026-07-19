from common.commands.abstract_base_command import AbstractBaseCommand
from mcp_server.forms import RegisterOAuthClientForm
from mcp_server.models import OAuthClient
from mcp_server.repositories import OAuthClientRepository


class RegisterOAuthClientCommand(AbstractBaseCommand):
    """Register a public OAuth client via dynamic registration."""

    def __init__(self, form: RegisterOAuthClientForm) -> None:
        self.form = form

    def execute(self) -> OAuthClient:
        super().execute()

        # BaseForm.clean() drops keys the client didn't submit, so the
        # RFC 7591-optional client_name defaults here rather than in the form.
        return OAuthClientRepository.create(
            client_name=self.form.cleaned_data.get("client_name") or "MCP Client",
            redirect_uris=self.form.cleaned_data["redirect_uris"],
        )
