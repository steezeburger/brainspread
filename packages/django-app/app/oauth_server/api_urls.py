from django.urls import path

from . import views

urlpatterns = [
    path("connections/", views.list_connections, name="list_oauth_connections"),
    path(
        "connections/revoke/",
        views.revoke_connection,
        name="revoke_oauth_connection",
    ),
]
