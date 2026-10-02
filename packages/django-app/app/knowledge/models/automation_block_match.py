from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class AutomationBlockMatch(UUIDModelMixin, CRUDTimestampsMixin):
    """Per-block dwell watermark for a ``when:: matched-for`` automation
    (issue #206's reactive slice).

    Schedule due-ness only asks "does this block match right now" — dwell
    ("matched the query for N minutes/days") needs to remember *when* a
    block first started matching, across ticks. One row per (automation,
    matched block) pair, deleted the moment a tick's query no longer
    includes that block, so re-matching later starts the dwell clock
    over. ``fingerprint`` is a snapshot of whatever fields/tags the
    automation's ``watch::`` prop names (see
    ``services.automation_when.compute_fingerprint``); a change there
    also resets the clock, since the block "changed" even though it
    never left the match set.

    Keyed by ``automation_block_uuid`` / ``matched_block_uuid`` (soft
    references, mirroring ``AutomationRun``) rather than hard FKs, so a
    row survives either block being edited or recreated.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="automation_block_matches",
    )
    automation_block_uuid = models.UUIDField(db_index=True)
    matched_block_uuid = models.UUIDField(db_index=True)
    first_matched_at = models.DateTimeField(
        help_text="When this block first started matching the automation's "
        "query (or last had a watched field change)",
    )
    fingerprint = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot of the automation's watch:: fields/tags at "
        "first_matched_at",
    )

    class Meta:
        db_table = "automation_block_matches"
        constraints = [
            models.UniqueConstraint(
                fields=["automation_block_uuid", "matched_block_uuid"],
                name="uniq_automation_block_match",
            )
        ]
        indexes = [models.Index(fields=["automation_block_uuid"])]

    def __str__(self) -> str:
        return (
            f"AutomationBlockMatch({self.automation_block_uuid}:"
            f"{self.matched_block_uuid})"
        )
