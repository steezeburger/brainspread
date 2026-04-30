from typing import TypedDict

from django.db import transaction
from django.db.models import Max

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.move_block_to_daily_form import MoveBlockToDailyForm
from ..forms.touch_page_form import TouchPageForm
from ..models import BlockData, PageData
from ..repositories import BlockRepository
from ..repositories.page_repository import PageRepository
from .touch_page_command import TouchPageCommand


class MoveBlockToDailyCommand(AbstractBaseCommand):
    """Command to move a single block (and its descendants) to a daily note page."""

    def __init__(self, form: MoveBlockToDailyForm) -> None:
        self.form = form

    def execute(self) -> "MoveBlockToDailyData":
        super().execute()  # validates the form

        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]
        target_date = self.form.cleaned_data.get("target_date") or today_for_user(user)

        target_page, _ = PageRepository.get_or_create_daily_note(user, target_date)

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
        # Capture before reassignment so we still know where the block came
        # from after block.page is repointed at target_page.
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

        # Bump modified_at on both ends of the move so each daily page sorts
        # to the top of the recent list when it loses or gains content.
        for page in {source_page, target_page}:
            touch_form = TouchPageForm(data={"user": user.id, "page": str(page.uuid)})
            if touch_form.is_valid():
                TouchPageCommand(touch_form).execute()

        return {
            "moved": True,
            "block": block.to_dict(),
            "target_page": target_page.to_dict(),
            "message": f"Moved block to {target_date.strftime('%Y-%m-%d')} page",
        }


class MoveBlockToDailyData(TypedDict):
    moved: bool
    block: BlockData
    target_page: PageData
    message: str
