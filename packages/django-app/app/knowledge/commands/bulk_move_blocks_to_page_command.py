from typing import List, TypedDict

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_move_blocks_to_page_form import BulkMoveBlocksToPageForm
from ..forms.move_block_to_page_form import MoveBlockToPageForm
from ..models import PageData
from ..repositories import BlockRepository
from .move_block_to_page_command import MoveBlockToPageCommand


class BulkMoveBlocksToPageCommand(AbstractBaseCommand):
    """Move a list of blocks to an arbitrary target page as siblings.

    Mirrors BulkMoveBlocksCommand but the target is an explicit page
    rather than a daily by date. Per-block hierarchy within the
    selection is preserved: blocks whose parent is also in the
    selection are not promoted — they ride along with the ancestor
    that MoveBlockToPageCommand drags through via
    BlockRepository.get_block_descendants. Top-level blocks (whose
    parent is not in the selection) are moved individually in
    document order so their relative order on the target page
    matches the source.
    """

    def __init__(self, form: BulkMoveBlocksToPageForm) -> None:
        self.form = form

    def execute(self) -> "BulkMoveBlocksToPageData":
        super().execute()

        user = self.form.cleaned_data["user"]
        uuids: List[str] = self.form.cleaned_data["blocks"]
        target_page = self.form.cleaned_data["target_page"]

        blocks_qs = BlockRepository.get_queryset().filter(user=user, uuid__in=uuids)
        blocks_by_uuid = {str(b.uuid): b for b in blocks_qs}
        selected_uuids = set(blocks_by_uuid.keys())

        # Find blocks whose parent isn't in the selection — those are the
        # "top" of the selected forest and the only ones we need to move
        # explicitly (their descendants follow). Order them in document
        # order: first by page, then by tree position, so siblings on
        # the same page stay adjacent and in their original sequence on
        # the target.
        top_blocks = [
            block
            for uuid_str, block in blocks_by_uuid.items()
            if not (block.parent and str(block.parent.uuid) in selected_uuids)
        ]
        top_blocks.sort(key=lambda b: (b.page_id, b.order, str(b.uuid)))

        moved = 0
        skipped = len(uuids) - len(selected_uuids)
        with transaction.atomic():
            for block in top_blocks:
                inner = MoveBlockToPageForm(
                    {
                        "user": user.id,
                        "block": str(block.uuid),
                        "target_page": str(target_page.uuid),
                    }
                )
                if not inner.is_valid():
                    skipped += 1
                    continue
                result = MoveBlockToPageCommand(inner).execute()
                if result.get("moved"):
                    moved += 1

        return {
            "moved_count": moved,
            "skipped_count": skipped,
            "target_page": target_page.to_dict(),
            "message": (
                f"Moved {moved} block{'s' if moved != 1 else ''} to "
                f"{target_page.title}"
            ),
        }


class BulkMoveBlocksToPageData(TypedDict):
    moved_count: int
    skipped_count: int
    target_page: PageData
    message: str
