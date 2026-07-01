from typing import Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class AutomationRun(UUIDModelMixin, CRUDTimestampsMixin):
    """A single execution of an automation (see issue #143).

    Automations themselves are defined in the graph as ``#automation``
    blocks (``key:: value`` props) — there is no separate definition
    model. This table is the runtime ledger: one row per run. It records
    what fired the run, the outcome, and any error, and doubles as the
    audit log and the idempotency guard for the schedule poller (mirrors
    the Reminder dispatch pattern from issue #59).

    Keyed by ``automation_block_uuid`` (a soft reference) rather than a
    hard FK so a run survives the user editing, re-creating, or deleting
    the defining block.
    """

    TRIGGER_SCHEDULE = "schedule"
    TRIGGER_MANUAL = "manual"
    TRIGGER_EVENT = "event"
    TRIGGER_WEBHOOK = "webhook"
    TRIGGER_CHOICES = [
        (TRIGGER_SCHEDULE, "Schedule"),
        (TRIGGER_MANUAL, "Manual"),
        (TRIGGER_EVENT, "Event"),
        (TRIGGER_WEBHOOK, "Webhook"),
    ]

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="automation_runs",
    )
    automation_block_uuid = models.UUIDField(
        db_index=True,
        help_text="UUID of the #automation block that defined this run",
    )
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(
        blank=True, default="", help_text="Failure detail, if any"
    )
    result = models.JSONField(
        default=dict,
        blank=True,
        help_text="Summary of what the run did (e.g. matched/affected counts)",
    )
    trigger_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="What fired the run (e.g. triggering block uuid, schedule slot)",
    )

    class Meta:
        db_table = "automation_runs"
        ordering = ("-created_at",)
        indexes = [
            # Latest-run lookup for a given automation (schedule due-ness
            # and the audit trail both key off this).
            models.Index(fields=["automation_block_uuid", "-created_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"AutomationRun({self.uuid}) {self.trigger} {self.status}"

    def to_dict(self) -> "AutomationRunData":
        return {
            "uuid": str(self.uuid),
            "automation_block_uuid": str(self.automation_block_uuid),
            "trigger": self.trigger,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_error": self.last_error,
            "result": self.result or {},
        }


class AutomationRunData(TypedDict):
    uuid: str
    automation_block_uuid: str
    trigger: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    last_error: str
    result: dict
