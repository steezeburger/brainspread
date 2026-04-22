from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin

from .ai_model import AIModel
from .chat_session import ChatSession


class PendingToolApproval(UUIDModelMixin, CRUDTimestampsMixin):
    """Paused state for a chat turn that emitted a write tool.

    The assistant requested one or more write tools (e.g. edit_block) that
    can't run without explicit user approval. We snapshot everything needed
    to resume the tool loop out-of-band: the conversation context, the
    paused assistant turn's content blocks (so we can re-send them verbatim
    as required by the Anthropic API), and the tool_uses awaiting a
    per-call decision.
    """

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="pending_approvals"
    )
    ai_model = models.ForeignKey(
        AIModel, on_delete=models.SET_NULL, null=True, blank=True
    )
    provider_name = models.CharField(max_length=50)
    system_prompt = models.TextField(blank=True, default="")
    # Conversation snapshot passed to the API for the paused turn, NOT
    # including the paused assistant turn itself (that's `assistant_blocks`).
    messages_snapshot = models.JSONField(default=list)
    # Paused assistant turn's content blocks (text, thinking, tool_use).
    assistant_blocks = models.JSONField(default=list)
    # Each: {tool_use_id, name, input, requires_approval}.
    tool_uses = models.JSONField(default=list)
    # Tool events produced earlier in this request (from prior turns in the
    # same tool loop), so the final assistant message records the full log.
    tool_events = models.JSONField(default=list)
    partial_text = models.TextField(blank=True, default="")
    partial_thinking = models.TextField(blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_creation_input_tokens = models.PositiveIntegerField(default=0)
    cache_read_input_tokens = models.PositiveIntegerField(default=0)
    # Tool scopes granted on the original request — reused on resume so the
    # model sees the same tool set after continuation.
    enable_notes_tools = models.BooleanField(default=False)
    enable_notes_write_tools = models.BooleanField(default=False)
    enable_web_search = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )

    class Meta:
        db_table = "ai_chat_pending_tool_approvals"
        ordering = ("-created_at",)
        verbose_name = "Pending Tool Approval"
        verbose_name_plural = "Pending Tool Approvals"
