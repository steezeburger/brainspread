from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("auth/login/", views.login, name="login"),
    path("auth/register/", views.register, name="register"),
    path("auth/logout/", views.logout, name="logout"),
    path("auth/me/", views.me, name="me"),
    path("auth/update-timezone/", views.update_timezone, name="update_timezone"),
    path("auth/update-theme/", views.update_theme, name="update_theme"),
    path(
        "auth/update-time-format/",
        views.update_time_format,
        name="update_time_format",
    ),
    path(
        "auth/update-discord-webhook/",
        views.update_discord_webhook,
        name="update_discord_webhook",
    ),
]
