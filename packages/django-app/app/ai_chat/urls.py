from django.urls import path

from . import views

app_name = "ai_chat"

urlpatterns = [
    path("send/", views.send_message, name="send_message"),
    path(
        "stream/",
        views.StreamSendMessageView.as_view(),
        name="stream_send_message",
    ),
    path("sessions/", views.chat_sessions, name="chat_sessions"),
    path(
        "sessions/<str:session_id>/",
        views.chat_session_detail,
        name="chat_session_detail",
    ),
    path("settings/", views.ai_settings, name="ai_settings"),
    path("settings/update/", views.update_ai_settings, name="update_ai_settings"),
]
