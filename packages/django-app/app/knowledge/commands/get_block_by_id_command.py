from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_block_by_id_form import GetBlockByIdForm
from ..repositories.block_repository import BlockRepository


class GetBlockByIdCommand(AbstractBaseCommand):
    """Fetch a single block by uuid plus its direct children."""

    def __init__(self, form: GetBlockByIdForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuid = self.form.cleaned_data["block_uuid"]

        block = BlockRepository.get_by_uuid(str(block_uuid), user=user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        children = BlockRepository.get_child_blocks(block)
        return {
            "block": {
                "block_uuid": str(block.uuid),
                "block_type": block.block_type,
                "content": block.content,
                "page_title": block.page.title if block.page else None,
                "page_slug": block.page.slug if block.page else None,
            },
            "children": [
                {
                    "block_uuid": str(child.uuid),
                    "block_type": child.block_type,
                    "content": child.content,
                    "order": child.order,
                }
                for child in children
            ],
        }
