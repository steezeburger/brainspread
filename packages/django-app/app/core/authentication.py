from typing import Optional

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.mcp_access_keys import is_mcp_access_key
from core.models import McpAccessToken, User
from core.repositories import McpAccessTokenRepository


class McpAccessTokenAuthentication(BaseAuthentication):
    """Authenticates ``Authorization: Bearer bsmcp_…`` (``Token bsmcp_…``
    works too, so a config copied from the legacy token instructions
    only needs the key swapped).

    Headers carrying anything other than an MCP access key are left for
    the next authentication class, which keeps legacy DRF tokens
    working on the MCP endpoint.
    """

    keywords = (b"bearer", b"token")

    def authenticate(self, request) -> Optional[tuple[User, McpAccessToken]]:
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() not in self.keywords:
            return None
        try:
            key = parts[1].decode()
        except UnicodeError:
            return None
        if not is_mcp_access_key(key):
            return None

        token = McpAccessTokenRepository.get_usable_by_key(key)
        if token is None:
            raise AuthenticationFailed("Invalid, expired, or revoked MCP access token.")
        McpAccessTokenRepository.mark_used(token)
        return token.user, token

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="brainspread-mcp"'
