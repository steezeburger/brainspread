"""DRF authentication for OAuth bearer tokens issued by this server."""

from typing import Optional, Tuple

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from core.models import User
from mcp_server.models import OAuthAccessToken
from mcp_server.repositories import OAuthAccessTokenRepository


def resource_metadata_url(request) -> str:
    issuer = request.build_absolute_uri("/").rstrip("/")
    return f"{issuer}/.well-known/oauth-protected-resource"


class OAuthBearerAuthentication(BaseAuthentication):
    """Authenticate ``Authorization: Bearer <token>`` against OAuth
    access tokens.

    Ordered *first* on the MCP endpoint so unauthenticated requests get
    a ``WWW-Authenticate: Bearer resource_metadata=...`` challenge —
    that header is how MCP clients discover the OAuth flow (RFC 9728).
    Requests using the legacy ``Token`` scheme fall through to DRF's
    TokenAuthentication untouched.
    """

    def authenticate(self, request) -> Optional[Tuple[User, OAuthAccessToken]]:
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed(
                "Invalid Authorization header. Expected 'Bearer <token>'."
            )
        try:
            raw_token = header[1].decode("ascii")
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed(
                "Invalid token characters in Authorization header."
            )

        token = OAuthAccessTokenRepository.get_active_by_access_token(raw_token)
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid or expired access token.")
        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")
        return (token.user, token)

    def authenticate_header(self, request) -> str:
        return f'Bearer resource_metadata="{resource_metadata_url(request)}"'
