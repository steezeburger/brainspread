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
    path(
        "approvals/<str:approval_id>/resume/",
        views.ResumeApprovalView.as_view(),
        name="resume_approval",
    ),
    path("sessions/", views.chat_sessions, name="chat_sessions"),
    path(
        "sessions/<str:session_id>/",
        views.chat_session_detail,
        name="chat_session_detail",
    ),
    path(
        "sessions/<str:session_id>/favorite/",
        views.set_chat_session_favorited,
        name="set_chat_session_favorited",
    ),
    path(
        "sessions/<str:session_id>/title/",
        views.update_chat_session_title,
        name="update_chat_session_title",
    ),
    path(
        "messages/<str:message_uuid>/follow/",
        views.FollowMessageView.as_view(),
        name="follow_message",
    ),
    path("settings/", views.ai_settings, name="ai_settings"),
    path("settings/update/", views.update_ai_settings, name="update_ai_settings"),
]
