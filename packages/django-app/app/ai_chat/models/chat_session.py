from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class ChatSession(UUIDModelMixin, CRUDTimestampsMixin):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "ai_chat_sessions"
        ordering = ("-created_at",)
        verbose_name = "Chat Session"
        verbose_name_plural = "Chat Sessions"


class ChatMessage(UUIDModelMixin, CRUDTimestampsMixin):
    STATUS_COMPLETE = "complete"
    STATUS_STREAMING = "streaming"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_COMPLETE, "Complete"),
        (STATUS_STREAMING, "Streaming"),
        (STATUS_ERROR, "Error"),
    ]

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20)  # 'user' or 'assistant'
    content = models.TextField()
    thinking = models.TextField(blank=True, default="")
    ai_model = models.ForeignKey(
        "ai_chat.AIModel", on_delete=models.SET_NULL, null=True, blank=True
    )
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cache_creation_input_tokens = models.PositiveIntegerField(null=True, blank=True)
    cache_read_input_tokens = models.PositiveIntegerField(null=True, blank=True)
    # Ordered list of tool events (tool_use / tool_result) captured while the
    # assistant was producing this message. Shape:
    #   [{"type": "tool_use", "tool_use_id": str, "name": str, "input": dict},
    #    {"type": "tool_result", "tool_use_id": str, "name": str, "result": dict}]
    tool_events = models.JSONField(default=list, blank=True)
    # Asset attachments (vision / file inputs). Persisted as metadata so the
    # UI can re-render images in history without touching the assets app and
    # so the SendMessage command can re-attach the bytes on subsequent turns.
    # Shape:
    #   [{"asset_uuid": str, "mime_type": str, "file_type": str,
    #     "byte_size": int, "original_filename": str}]
    attachments = models.JSONField(default=list, blank=True)
    # Lifecycle of an assistant message. Most rows are 'complete' (the
    # legacy default — no migration needed for existing data). 'streaming'
    # rows are in-flight responses that the client can reconnect to via
    # the message-follow endpoint after a page reload. 'error' rows are
    # streams that aborted before completion; their content holds whatever
    # was generated before the failure.
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COMPLETE,
        db_index=True,
    )

    class Meta:
        db_table = "ai_chat_messages"
        ordering = ("created_at",)
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
