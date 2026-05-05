from typing import Optional, TypedDict

from django.db import models
from django.utils import timezone

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class Reminder(UUIDModelMixin, CRUDTimestampsMixin):
    """A time-based ping for a block.

    Reminders are separate from a block's due date (`scheduled_for`):
    `scheduled_for` decides *where* a block surfaces; a Reminder decides
    *when to ping* the user. A block can have 0..N reminders, or reminders
    without a due date.
    """

    CHANNEL_DISCORD_WEBHOOK = "discord_webhook"
    CHANNEL_CHOICES = [
        (CHANNEL_DISCORD_WEBHOOK, "Discord Webhook"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    block = models.ForeignKey(
        "knowledge.Block", on_delete=models.CASCADE, related_name="reminders"
    )
    fire_at = models.DateTimeField(
        help_text="When this reminder should fire (UTC)",
    )
    channel = models.CharField(
        max_length=32, choices=CHANNEL_CHOICES, default=CHANNEL_DISCORD_WEBHOOK
    )
    sent_at = models.DateTimeField(
        null=True, blank=True, help_text="When this reminder was delivered"
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    last_error = models.TextField(
        blank=True, default="", help_text="Last delivery error, if any"
    )

    class Meta:
        db_table = "reminders"
        ordering = ("fire_at",)
        indexes = [
            # Poll predicate used by the scheduler.
            models.Index(fields=["status", "fire_at"]),
            models.Index(fields=["block"]),
        ]

    def __str__(self):
        return f"Reminder({self.uuid}) {self.channel} @ {self.fire_at}"

    def cancel(self) -> "Reminder":
        """Mark this reminder cancelled. Sets sent_at alongside status so
        the block-level pending-reminder lookup (which keys off
        sent_at IS NULL) treats it as no-longer-pending."""
        now = timezone.now()
        self.status = self.STATUS_CANCELLED
        self.sent_at = now
        self.save(update_fields=["status", "sent_at", "modified_at"])
        return self

    def to_dict(self) -> "ReminderData":
        return {
            "uuid": str(self.uuid),
            "block_uuid": str(self.block.uuid),
            "fire_at": self.fire_at.isoformat(),
            "channel": self.channel,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class ReminderData(TypedDict):
    uuid: str
    block_uuid: str
    fire_at: str
    channel: str
    status: str
    sent_at: Optional[str]
