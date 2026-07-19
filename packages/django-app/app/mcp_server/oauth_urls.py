"""Root-level OAuth routes for the MCP server.

Included at "" in the project URLconf because the .well-known
discovery documents must live at the domain root (RFC 8414/9728).
The re_paths accept the path-suffixed discovery variants clients
derive from the resource URL (/.well-known/...-resource/api/mcp)
with or without a trailing slash.
"""

from django.urls import path, re_path

from . import oauth_views

app_name = "mcp_oauth"

urlpatterns = [
    re_path(
        r"^\.well-known/oauth-authorization-server(?P<suffix>/api/mcp/?)?$",
        oauth_views.authorization_server_metadata,
        name="authorization_server_metadata",
    ),
    re_path(
        r"^\.well-known/oauth-protected-resource(?P<suffix>/api/mcp/?)?$",
        oauth_views.protected_resource_metadata,
        name="protected_resource_metadata",
    ),
    path("oauth/register", oauth_views.register_client, name="register_client"),
    path("oauth/authorize", oauth_views.authorize, name="authorize"),
    path("oauth/token", oauth_views.token, name="token"),
]
