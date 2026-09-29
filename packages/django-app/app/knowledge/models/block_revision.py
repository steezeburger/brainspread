from typing import Optional, TypedDict

from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class BlockRevision(UUIDModelMixin, CRUDTimestampsMixin):
    """One past state of a block's tracked fields (issue #234).

    Append-only history. A row is written by ``BlockRevisionRepository``
    when a command is about to overwrite a tracked field with a different
    value — the row stores the value being superseded, not the new one.
    That means the newest revision for a block is "what these fields
    looked like right before the most recent edit", which is exactly what
    a user wants when they say "I just cleared this, what did it say?".

    Restoring writes a past revision's values back onto the live block
    (through the normal update path) and that write itself produces a new
    revision capturing the state just before the restore — history is
    append-only, so a restore can itself be undone.
    """

    SOURCE_USER = "user"
    SOURCE_AUTOMATION = "automation"
    SOURCE_ASSISTANT = "assistant"
    SOURCE_SYSTEM = "system"
    SOURCE_CHOICES = [
        (SOURCE_USER, "User"),
        (SOURCE_AUTOMATION, "Automation"),
        (SOURCE_ASSISTANT, "Assistant"),
        (SOURCE_SYSTEM, "System"),
    ]

    # Tracked fields — kept in sync with BlockRevisionRepository.TRACKED_FIELDS.
    # Moves/reorders (page, parent, order) and collapsed are deliberately
    # not tracked (issue #234).
    block = models.ForeignKey(
        "Block", on_delete=models.CASCADE, related_name="revisions"
    )
    content = models.TextField(blank=True)
    block_type = models.CharField(max_length=20)
    properties = models.JSONField(default=dict, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    due_at_has_time = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_USER
    )

    class Meta:
        db_table = "block_revisions"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["block", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"BlockRevision {self.uuid} for block {self.block_id}"

    def to_dict(self) -> "BlockRevisionData":
        return {
            "uuid": str(self.uuid),
            "block_uuid": str(self.block.uuid),
            "content": self.content,
            "block_type": self.block_type,
            "properties": self.properties or {},
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "due_at_has_time": self.due_at_has_time,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        }


class BlockRevisionData(TypedDict):
    uuid: str
    block_uuid: str
    content: str
    block_type: str
    properties: dict
    due_at: Optional[str]
    due_at_has_time: bool
    completed_at: Optional[str]
    source: str
    created_at: str
