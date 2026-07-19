import base64
import hashlib
import hmac
from typing import NamedTuple

from common.commands.abstract_base_command import AbstractBaseCommand
from mcp_server.constants import ACCESS_TOKEN_LIFETIME
from mcp_server.exceptions import OAuthError
from mcp_server.forms import ExchangeAuthorizationCodeForm
from mcp_server.models import OAuthAccessToken
from mcp_server.repositories import (
    OAuthAccessTokenRepository,
    OAuthAuthorizationCodeRepository,
)


class TokenResult(NamedTuple):
    token: OAuthAccessToken
    expires_in: int


def _pkce_challenge_from_verifier(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class ExchangeAuthorizationCodeCommand(AbstractBaseCommand):
    """Exchange an authorization code + PKCE verifier for tokens.

    Raises OAuthError with RFC 6749 error codes; the token view maps
    those onto the JSON error responses the spec requires.
    """

    def __init__(self, form: ExchangeAuthorizationCodeForm) -> None:
        self.form = form

    def execute(self) -> TokenResult:
        super().execute()

        data = self.form.cleaned_data
        auth_code = OAuthAuthorizationCodeRepository.get_by_code(data["code"])
        if auth_code is None:
            raise OAuthError("invalid_grant", "unknown authorization code")
        if auth_code.is_used:
            # Replayed code — revoke nothing here (we can't tell which
            # party is the attacker) but refuse the exchange.
            raise OAuthError("invalid_grant", "authorization code already used")
        if auth_code.is_expired:
            raise OAuthError("invalid_grant", "authorization code expired")
        if auth_code.client.client_id != data["client_id"]:
            raise OAuthError("invalid_client", "client_id mismatch")
        if auth_code.redirect_uri != data["redirect_uri"]:
            raise OAuthError("invalid_grant", "redirect_uri mismatch")

        expected = auth_code.code_challenge
        actual = _pkce_challenge_from_verifier(data["code_verifier"])
        if not hmac.compare_digest(expected, actual):
            raise OAuthError("invalid_grant", "PKCE verification failed")

        OAuthAuthorizationCodeRepository.mark_used(auth_code)
        token = OAuthAccessTokenRepository.create_for_user(
            client=auth_code.client, user=auth_code.user
        )
        return TokenResult(
            token=token, expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds())
        )
