from typing import List, TypedDict

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_delete_blocks_form import BulkDeleteBlocksForm
from ..forms.delete_block_form import DeleteBlockForm
from ..repositories import BlockRepository
from .delete_block_command import DeleteBlockCommand


class BulkDeleteBlocksCommand(AbstractBaseCommand):
    """Delete a list of blocks in a single transaction.

    Delegates each block to ``DeleteBlockCommand`` so the existing archive
    cascade and per-block validation rules are reused. Blocks whose ancestor
    is also in the selection are skipped — the model's CASCADE on parent will
    take them with the ancestor and a second delete would be a no-op anyway.
    """

    def __init__(self, form: BulkDeleteBlocksForm) -> None:
        self.form = form

    def execute(self) -> "BulkDeleteBlocksData":
        super().execute()

        user = self.form.cleaned_data["user"]
        uuids: List[str] = self.form.cleaned_data["blocks"]

        blocks_qs = BlockRepository.get_queryset().filter(user=user, uuid__in=uuids)
        blocks_by_uuid = {str(b.uuid): b for b in blocks_qs}

        selected_uuids = set(blocks_by_uuid.keys())

        # Skip blocks that have an ancestor also in the selection — deleting
        # the ancestor cascades through the FK with on_delete=CASCADE.
        roots: List[str] = []
        for uuid_str, block in blocks_by_uuid.items():
            current = block.parent
            covered = False
            while current is not None:
                if str(current.uuid) in selected_uuids:
                    covered = True
                    break
                current = current.parent
            if not covered:
                roots.append(uuid_str)

        deleted = 0
        skipped = len(uuids) - len(selected_uuids)
        with transaction.atomic():
            for uuid_str in roots:
                inner = DeleteBlockForm({"user": user.id, "block": uuid_str})
                if not inner.is_valid():
                    skipped += 1
                    continue
                DeleteBlockCommand(inner).execute()
                deleted += 1

        return {
            "deleted_count": deleted,
            "skipped_count": skipped,
            "message": f"Deleted {deleted} block{'s' if deleted != 1 else ''}",
        }


class BulkDeleteBlocksData(TypedDict):
    deleted_count: int
    skipped_count: int
    message: str
