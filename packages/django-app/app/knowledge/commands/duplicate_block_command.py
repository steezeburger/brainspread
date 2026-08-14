from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.duplicate_block_form import DuplicateBlockForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block
from ..repositories import BlockRepository
from .touch_page_command import TouchPageCommand


class DuplicateBlockCommand(AbstractBaseCommand):
    """Duplicate a block (and its descendant subtree) as a new sibling
    directly below it — Cmd+D."""

    def __init__(self, form: DuplicateBlockForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]

        with transaction.atomic():
            if block.parent:
                siblings = BlockRepository.get_child_blocks(block.parent)
            else:
                siblings = BlockRepository.get_root_blocks(block.page)

            new_order = block.order + 1
            reorder_data = [
                {"uuid": str(sibling.uuid), "order": sibling.order + 1}
                for sibling in siblings
                if sibling.uuid != block.uuid and sibling.order >= new_order
            ]
            if reorder_data:
                BlockRepository.reorder_blocks(reorder_data, user=user)

            clone = BlockRepository.clone_block(
                block, parent=block.parent, order=new_order, target_user=user
            )

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return clone
