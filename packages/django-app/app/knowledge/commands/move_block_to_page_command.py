from typing import TypedDict

from django.core.exceptions import ValidationError
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

    With ``target_parent`` set the block nests under that block instead
    of landing at the page root — the "move under…" flow. The order is
    then scoped to the parent's children (last child) rather than the
    page-wide max.
    """

    def __init__(self, form: MoveBlockToPageForm) -> None:
        self.form = form

    def execute(self) -> "MoveBlockToPageData":
        super().execute()

        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]
        target_page = self.form.cleaned_data["target_page"]
        target_parent = self.form.cleaned_data.get("target_parent")

        target_parent_id = target_parent.pk if target_parent else None
        already_in_place = (
            block.page_id == target_page.pk and block.parent_id == target_parent_id
        )
        if already_in_place:
            return {
                "moved": False,
                "block": block.to_dict(),
                "target_page": target_page.to_dict(),
                "message": "Block is already in the target position",
            }

        if target_parent and self._would_create_circular_reference(
            block, target_parent
        ):
            raise ValidationError(
                "Cannot move a block under itself or one of its descendants"
            )

        descendants = BlockRepository.get_block_descendants(block)
        # Capture before reassignment so we can touch the source page after
        # block.page is repointed at target_page.
        source_page = block.page

        with transaction.atomic():
            order_scope = BlockRepository.get_queryset().filter(page=target_page)
            if target_parent:
                order_scope = order_scope.filter(parent=target_parent)
            max_order = order_scope.aggregate(max_order=Max("order"))["max_order"]
            max_order = max_order if max_order is not None else 0

            block.page = target_page
            block.parent = target_parent
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

    def _would_create_circular_reference(self, block, proposed_parent) -> bool:
        """True when proposed_parent is the block itself or lives inside
        the block's subtree — nesting there would detach the subtree
        from the page tree entirely."""
        current = proposed_parent
        while current is not None:
            if current.pk == block.pk:
                return True
            current = current.parent
        return False


class MoveBlockToPageData(TypedDict):
    moved: bool
    block: BlockData
    target_page: PageData
    message: str
