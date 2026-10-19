from django.urls import path, re_path

from . import views

urlpatterns = [
    path(
        "oauth-authorization-server",
        views.authorization_server_metadata,
        name="oauth_authorization_server_metadata",
    ),
    path(
        "oauth-protected-resource",
        views.protected_resource_metadata,
        name="oauth_protected_resource_metadata",
    ),
    re_path(
        r"^oauth-protected-resource/(?P<resource_path>.*)$",
        views.protected_resource_metadata,
    ),
]
