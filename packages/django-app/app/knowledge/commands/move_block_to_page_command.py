from typing import TypedDict

from django.db import transaction
from django.db.models import Max

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.move_block_to_page_form import MoveBlockToPageForm
from ..forms.touch_page_form import TouchPageForm
from ..models import BlockData, PageData
from ..repositories import BlockRepository
from .touch_page_command import TouchPageCommand


class MoveBlockToPageCommand(AbstractBaseCommand):
    """Move a single block (and its descendants) to an explicit target page.

    Mirrors MoveBlockToDailyCommand's mechanics — promote to root on the
    target, land at the bottom of the existing order, carry descendants
    along, touch both pages so they bubble to the top of Recent — but
    accepts an arbitrary target page rather than resolving by date.
    """

    def __init__(self, form: MoveBlockToPageForm) -> None:
        self.form = form

    def execute(self) -> "MoveBlockToPageData":
        super().execute()

        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]
        target_page = self.form.cleaned_data["target_page"]

        already_root_on_target = (
            block.page_id == target_page.pk and block.parent_id is None
        )
        if already_root_on_target:
            return {
                "moved": False,
                "block": block.to_dict(),
                "target_page": target_page.to_dict(),
                "message": "Block is already on the target page",
            }

        descendants = BlockRepository.get_block_descendants(block)
        # Capture before reassignment so we can touch the source page after
        # block.page is repointed at target_page.
        source_page = block.page

        with transaction.atomic():
            max_order = (
                BlockRepository.get_queryset()
                .filter(page=target_page)
                .aggregate(max_order=Max("order"))["max_order"]
            )
            max_order = max_order if max_order is not None else 0

            block.page = target_page
            block.parent = None
            block.order = max_order + 1
            block.save(update_fields=["page", "parent", "order"])

            for descendant in descendants:
                descendant.page = target_page
                descendant.save(update_fields=["page"])

        for page in {source_page, target_page}:
            touch_form = TouchPageForm(data={"user": user.id, "page": str(page.uuid)})
            if touch_form.is_valid():
                TouchPageCommand(touch_form).execute()

        return {
            "moved": True,
            "block": block.to_dict(),
            "target_page": target_page.to_dict(),
            "message": f"Moved block to {target_page.title}",
        }


class MoveBlockToPageData(TypedDict):
    moved: bool
    block: BlockData
    target_page: PageData
    message: str
