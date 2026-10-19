from typing import Optional

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.models import User

from .constants import ACCESS_TOKEN_PREFIX, MCP_SCOPE
from .helpers import hash_secret, resource_metadata_url
from .models import OAuthToken
from .repositories import OAuthTokenRepository


class OAuthAccessTokenAuthentication(BaseAuthentication):
    """Authenticates ``Authorization: Bearer bsat_…`` access tokens issued
    by the OAuth token endpoint.

    Other credentials fall through to the next authentication class.
    This class goes first on the MCP endpoint because DRF builds the
    401's ``WWW-Authenticate`` header from the first class, and that
    header is how MCP clients discover the OAuth server (RFC 9728).
    """

    def authenticate(self, request) -> Optional[tuple[User, OAuthToken]]:
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        try:
            access_token = parts[1].decode()
        except UnicodeError:
            return None
        if not access_token.startswith(ACCESS_TOKEN_PREFIX):
            return None

        token = OAuthTokenRepository.get_usable_by_access_hash(
            hash_secret(access_token)
        )
        if token is None:
            raise AuthenticationFailed("Invalid or expired access token.")
        OAuthTokenRepository.mark_used(token)
        return token.user, token

    def authenticate_header(self, request) -> str:
        metadata_url = resource_metadata_url(request, request.path)
        return f'Bearer resource_metadata="{metadata_url}", scope="{MCP_SCOPE}"'
