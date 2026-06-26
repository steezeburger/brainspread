"""DRF authentication for OAuth-issued MCP access tokens.

Wraps django-oauth-toolkit's Bearer-token authentication so the 401
challenge advertises *where* to discover the OAuth flow, per the MCP
spec: ``WWW-Authenticate: Bearer resource_metadata="<PRM url>"``. A
client that has never authenticated follows that pointer to begin the
authorization-code dance.
"""

from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework.request import Request

from .oauth_metadata import protected_resource_metadata_url


class MCPBearerAuthentication(OAuth2Authentication):
    def authenticate_header(self, request: Request) -> str:
        metadata_url = protected_resource_metadata_url(request)
        return f'Bearer resource_metadata="{metadata_url}"'
