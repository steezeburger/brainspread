import secrets
from datetime import timedelta
from typing import Optional

from django.db import models
from django.utils import timezone

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


def _generate_token() -> str:
    # ~256 bits of entropy. token_urlsafe is path-safe so the token can
    # ride directly in the URL without encoding.
    return secrets.token_urlsafe(32)


class ReminderAction(UUIDModelMixin, CRUDTimestampsMixin):
    """Single-use reply action attached to a delivered reminder.

    When `SendDueRemindersCommand` ships a reminder to Discord it also
    mints a small set of action rows (one per supported action). Each
    row carries an unguessable `token` that resolves to a specific
    (reminder, action) pair. Clicking the corresponding link in the
    Discord message hits the public `reminder_action` view, which
    consumes the token and performs the action — see
    `ConsumeReminderActionCommand`.

    Tokens are intentionally narrow: a token can only run its bound
    action on its bound reminder. Possessing one doesn't grant any
    other access. They expire shortly after delivery (default 7d) and
    flip to single-use the moment they're consumed.
    """

    ACTION_COMPLETE = "complete"
    ACTION_SNOOZE_1H = "snooze_1h"
    ACTION_SNOOZE_1D = "snooze_1d"
    ACTION_CHOICES = [
        (ACTION_COMPLETE, "Mark complete"),
        (ACTION_SNOOZE_1H, "Snooze 1 hour"),
        (ACTION_SNOOZE_1D, "Snooze 1 day"),
    ]

    DEFAULT_TTL = timedelta(days=7)

    reminder = models.ForeignKey(
        "knowledge.Reminder",
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    # `unique=True` doubles as the lookup index — the public view
    # resolves a click by token alone.
    token = models.CharField(max_length=64, unique=True, default=_generate_token)
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the token was consumed (single-use)",
    )
    expires_at = models.DateTimeField(
        help_text="After this point the token is rejected",
    )

    class Meta:
        db_table = "reminder_actions"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["reminder"]),
        ]

    def __str__(self) -> str:
        return f"ReminderAction({self.uuid}) {self.action}"

    def is_usable(self, *, now: Optional["timezone.datetime"] = None) -> bool:
        moment = now or timezone.now()
        return self.used_at is None and moment < self.expires_at

    def mark_used(self, *, now: Optional["timezone.datetime"] = None) -> None:
        moment = now or timezone.now()
        self.used_at = moment
        self.save(update_fields=["used_at", "modified_at"])
