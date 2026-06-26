"""Commands for the MCP OAuth flow."""

from typing import Any

from common.commands.abstract_base_command import AbstractBaseCommand

from .forms import OAuthClientRegistrationForm
from .repositories import OAuthApplicationRepository


class RegisterOAuthClientCommand(AbstractBaseCommand):
    """Create an OAuth client from a Dynamic Client Registration request.

    Returns the RFC 7591 registration response. MCP clients are public
    (PKCE) by default; a client that asks for a secret-based auth method
    gets a confidential client and its one-time secret.
    """

    def __init__(self, form: OAuthClientRegistrationForm) -> None:
        self.form = form

    def execute(self) -> dict[str, Any]:
        super().execute()
        data = self.form.cleaned_data

        redirect_uris: list[str] = data["redirect_uris"]
        requested_method = (data.get("token_endpoint_auth_method") or "none").strip()
        confidential = requested_method != "none"
        name = (data.get("client_name") or "").strip() or "MCP Client"

        application, secret = OAuthApplicationRepository.create_client(
            name=name,
            redirect_uris=redirect_uris,
            confidential=confidential,
        )

        response: dict[str, Any] = {
            "client_id": application.client_id,
            "client_id_issued_at": int(application.created.timestamp()),
            "client_name": application.name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": (
                "client_secret_post" if confidential else "none"
            ),
            "scope": data.get("scope") or "mcp",
        }
        if confidential and secret:
            response["client_secret"] = secret
            # 0 ⇒ never expires (RFC 7591).
            response["client_secret_expires_at"] = 0
        return response
