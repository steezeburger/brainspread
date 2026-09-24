from datetime import timedelta
from typing import TypedDict

from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.purge_expired_trash_form import (
    DEFAULT_RETENTION_DAYS,
    PurgeExpiredTrashForm,
)
from ..models import Block, Page
from ..repositories import BlockRepository, PageRepository


class PurgeExpiredTrashData(TypedDict):
    pages_purged: int
    blocks_purged: int


class PurgeExpiredTrashCommand(AbstractBaseCommand):
    """Hard-delete Trash items past the retention window (issue #122).

    Blocks are purged first, on their own deleted_at. Pages are purged
    second — hard-deleting an expired page cascades (on_delete=CASCADE)
    to whatever blocks still live on it, active or not, so any block
    that only became inactive via that page's archive (and hasn't
    independently aged out yet) gets swept up in the same pass rather
    than lingering as an orphaned-looking row. Running blocks first
    also keeps "blocks_purged" accurate: a block old enough to purge on
    its own gets counted there even when its page is expiring in the
    same run, instead of silently riding along inside the page's
    cascade and going uncounted.
    """

    def __init__(self, form: PurgeExpiredTrashForm) -> None:
        self.form = form

    def execute(self) -> PurgeExpiredTrashData:
        super().execute()

        now = self.form.cleaned_data.get("now") or timezone.now()
        retention_days = (
            self.form.cleaned_data.get("retention_days") or DEFAULT_RETENTION_DAYS
        )
        cutoff = now - timedelta(days=retention_days)

        # A hard-delete queryset .delete() returns (total_count, {label:
        # count}) across every cascaded model, unlike the soft-delete
        # path's plain int from .update() — pull out just the row count
        # for the model actually being purged in each step.
        _, block_breakdown = BlockRepository.get_purgeable(cutoff).delete(
            force_delete=True
        )
        _, page_breakdown = PageRepository.get_purgeable(cutoff).delete(
            force_delete=True
        )

        return {
            "pages_purged": page_breakdown.get(Page._meta.label, 0),
            "blocks_purged": block_breakdown.get(Block._meta.label, 0),
        }
