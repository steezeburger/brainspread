"""URL patterns for the MCP OAuth authorization server.

``oauth2_patterns`` mounts only django-oauth-toolkit's protocol
endpoints (not its session-based application-management UI) under a
namespace, and is included at ``/o/`` by the root URLconf.

``root_urlpatterns`` are served from the site root: the two
``.well-known`` discovery documents (which must live at the origin
root), the dynamic-registration endpoint, and the login page that
``/o/authorize/`` redirects to.
"""

from django.contrib.auth import views as auth_views
from django.urls import path, re_path
from oauth2_provider import views as oauth2_views

from . import oauth_views

oauth2_patterns = (
    [
        path("authorize/", oauth2_views.AuthorizationView.as_view(), name="authorize"),
        path("token/", oauth2_views.TokenView.as_view(), name="token"),
        path(
            "revoke_token/",
            oauth2_views.RevokeTokenView.as_view(),
            name="revoke-token",
        ),
        path(
            "introspect/",
            oauth2_views.IntrospectTokenView.as_view(),
            name="introspect",
        ),
    ],
    "oauth2_provider",
)

root_urlpatterns = [
    re_path(
        r"^\.well-known/oauth-authorization-server/?$",
        oauth_views.authorization_server_metadata_view,
        name="oauth-authorization-server-metadata",
    ),
    re_path(
        r"^\.well-known/oauth-protected-resource(?:/api/mcp)?/?$",
        oauth_views.protected_resource_metadata_view,
        name="oauth-protected-resource-metadata",
    ),
    path("oauth/register", oauth_views.register_view, name="oauth-register"),
    path(
        "oauth/login/",
        auth_views.LoginView.as_view(
            template_name="mcp_oauth/login.html",
            authentication_form=oauth_views.EmailLoginForm,
        ),
        name="oauth-login",
    ),
]
