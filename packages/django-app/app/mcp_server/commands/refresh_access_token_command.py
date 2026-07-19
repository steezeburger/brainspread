from common.commands.abstract_base_command import AbstractBaseCommand
from mcp_server.commands.exchange_authorization_code_command import TokenResult
from mcp_server.constants import ACCESS_TOKEN_LIFETIME
from mcp_server.exceptions import OAuthError
from mcp_server.forms import RefreshAccessTokenForm
from mcp_server.repositories import OAuthAccessTokenRepository


class RefreshAccessTokenCommand(AbstractBaseCommand):
    """Rotate a refresh token into a fresh access/refresh pair.

    The old pair is revoked before the new one is issued, so a stolen
    refresh token dies the moment the legitimate client refreshes.
    """

    def __init__(self, form: RefreshAccessTokenForm) -> None:
        self.form = form

    def execute(self) -> TokenResult:
        super().execute()

        data = self.form.cleaned_data
        old = OAuthAccessTokenRepository.get_active_by_refresh_token(
            data["refresh_token"]
        )
        if old is None:
            raise OAuthError("invalid_grant", "unknown or revoked refresh token")
        if old.client.client_id != data["client_id"]:
            raise OAuthError("invalid_client", "client_id mismatch")

        OAuthAccessTokenRepository.revoke(old)
        token = OAuthAccessTokenRepository.create_for_user(
            client=old.client, user=old.user
        )
        return TokenResult(
            token=token, expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds())
        )
