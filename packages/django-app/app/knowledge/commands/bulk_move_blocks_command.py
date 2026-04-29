from typing import List, TypedDict

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.bulk_move_blocks_form import BulkMoveBlocksForm
from ..forms.move_block_to_daily_form import MoveBlockToDailyForm
from ..models import PageData
from ..repositories import BlockRepository
from ..repositories.page_repository import PageRepository
from .move_block_to_daily_command import MoveBlockToDailyCommand


class BulkMoveBlocksCommand(AbstractBaseCommand):
    """Move a list of blocks to a daily note as siblings.

    Per-block hierarchy within the selection is preserved: blocks whose
    parent is also in the selection are not promoted - they ride along with
    the ancestor that ``MoveBlockToDailyCommand`` already drags through via
    ``get_block_descendants``. Top-level blocks (whose parent is not in the
    selection) are moved individually in document order so their relative
    order on the target page matches the source.
    """

    def __init__(self, form: BulkMoveBlocksForm) -> None:
        self.form = form

    def execute(self) -> "BulkMoveBlocksData":
        super().execute()

        user = self.form.cleaned_data["user"]
        uuids: List[str] = self.form.cleaned_data["blocks"]
        target_date = self.form.cleaned_data.get("target_date") or today_for_user(user)

        target_page, _ = PageRepository.get_or_create_daily_note(user, target_date)

        blocks_qs = BlockRepository.get_queryset().filter(user=user, uuid__in=uuids)
        blocks_by_uuid = {str(b.uuid): b for b in blocks_qs}
        selected_uuids = set(blocks_by_uuid.keys())

        # Find blocks whose parent isn't in the selection — those are the
        # "top" of the selected forest and the only ones we need to move
        # explicitly (their descendants follow). Order them in document
        # order: first by page, then by tree position, so siblings on the
        # same page stay adjacent and in their original sequence on the
        # target.
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
                inner = MoveBlockToDailyForm(
                    {
                        "user": user.id,
                        "block": str(block.uuid),
                        "target_date": target_date,
                    }
                )
                if not inner.is_valid():
                    skipped += 1
                    continue
                result = MoveBlockToDailyCommand(inner).execute()
                if result.get("moved"):
                    moved += 1

        return {
            "moved_count": moved,
            "skipped_count": skipped,
            "target_page": target_page.to_dict(),
            "message": (
                f"Moved {moved} block{'s' if moved != 1 else ''} to "
                f"{target_date.strftime('%Y-%m-%d')}"
            ),
        }


class BulkMoveBlocksData(TypedDict):
    moved_count: int
    skipped_count: int
    target_page: PageData
    message: str
