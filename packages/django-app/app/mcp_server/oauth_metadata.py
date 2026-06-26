"""OAuth 2.1 discovery metadata for the MCP authorization flow.

These helpers build the JSON documents an MCP client fetches to learn
*how* to authenticate before it ever sends a request to the protected
``/api/mcp/`` endpoint:

- Protected Resource Metadata (RFC 9728) — points the client at the
  authorization server(s) that issue tokens for this resource.
- Authorization Server Metadata (RFC 8414) — advertises the authorize,
  token, and dynamic-registration endpoints plus the PKCE method.

The public origin is taken from ``settings.MCP_OAUTH_ISSUER`` when set
(the reliable choice behind a TLS-terminating proxy) and otherwise
derived from the incoming request.
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest

# The MCP endpoint, relative to the public origin. This is the OAuth
# "resource" that issued tokens are bound to.
MCP_RESOURCE_PATH = "/api/mcp"

# Single scope — holding a valid token grants access to the caller's own
# notes and tools. Finer-grained scopes can be added later.
MCP_SCOPE = "mcp"


def public_base_url(request: HttpRequest) -> str:
    """The public origin (``https://host``) with no trailing slash."""
    configured = getattr(settings, "MCP_OAUTH_ISSUER", "") or ""
    if configured:
        return configured.rstrip("/")
    return f"{request.scheme}://{request.get_host()}"


def mcp_resource_url(request: HttpRequest) -> str:
    return public_base_url(request) + MCP_RESOURCE_PATH


def protected_resource_metadata_url(request: HttpRequest) -> str:
    """Where the PRM document lives (advertised in ``WWW-Authenticate``)."""
    return public_base_url(request) + "/.well-known/oauth-protected-resource/api/mcp"


def protected_resource_metadata(request: HttpRequest) -> dict[str, Any]:
    base = public_base_url(request)
    return {
        "resource": base + MCP_RESOURCE_PATH,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [MCP_SCOPE],
        "resource_documentation": base + "/api/mcp/",
    }


def authorization_server_metadata(request: HttpRequest) -> dict[str, Any]:
    base = public_base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": base + "/o/authorize/",
        "token_endpoint": base + "/o/token/",
        "registration_endpoint": base + "/oauth/register",
        "revocation_endpoint": base + "/o/revoke_token/",
        "scopes_supported": [MCP_SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }
