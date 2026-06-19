from django.urls import path

from . import views

app_name = "mcp_server"

urlpatterns = [
    path("", views.mcp_endpoint, name="endpoint"),
]
