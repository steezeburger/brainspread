from typing import Dict, Optional

from django.db.models import QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import Block, BlockRevision

# Kept in sync with BlockRevision's field list. Moves/reorders (page,
# parent, order) and collapsed are deliberately excluded (issue #234) —
# indent/outdent and drag-reorder saves send unchanged content constantly
# and would otherwise flood the history with no-op entries.
TRACKED_FIELDS = (
    "content",
    "block_type",
    "properties",
    "due_at",
    "due_at_has_time",
    "completed_at",
)


class BlockRevisionRepository(BaseRepository):
    model = BlockRevision

    @classmethod
    def snapshot(cls, block: Block) -> Dict[str, object]:
        """Capture ``block``'s tracked-field values before a command
        mutates them in memory. Pass the result to ``record_if_changed``
        after the command has applied and saved its changes."""
        return {field: getattr(block, field) for field in TRACKED_FIELDS}

    @classmethod
    def record_if_changed(
        cls, block: Block, previous: Dict[str, object], source: str
    ) -> Optional[BlockRevision]:
        """Write a revision holding ``previous``'s values — the state
        being superseded — if any tracked field differs from ``block``'s
        current (already-saved) value. No-op otherwise, so a save that
        only touches untracked fields (order, parent, page, collapsed)
        never writes history."""
        changed = any(
            previous[field] != getattr(block, field) for field in TRACKED_FIELDS
        )
        if not changed:
            return None
        return cls.model.objects.create(block=block, source=source, **previous)

    @classmethod
    def list_for_block(cls, block: Block) -> QuerySet:
        """A block's revisions, newest first."""
        return (
            cls.get_queryset()
            .filter(block=block)
            .select_related("block")
            .order_by("-created_at")
        )

    @classmethod
    def get_by_uuid(
        cls, uuid: str, block: Optional[Block] = None
    ) -> Optional[BlockRevision]:
        queryset = cls.get_queryset().select_related("block")
        if block is not None:
            queryset = queryset.filter(block=block)
        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None
