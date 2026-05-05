from typing import Any, Dict, List, Optional

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_block_form import CreateBlockForm
from ..forms.create_blocks_bulk_form import CreateBlocksBulkForm
from ..models import Block, Page
from ..repositories import BlockRepository
from .create_block_command import CreateBlockCommand


class CreateBlocksBulkCommand(AbstractBaseCommand):
    """Create N blocks under a single parent (or page root) in one
    approval. Wraps CreateBlockCommand per row so prefix handling and
    page-touch behaviour stays in one place. The full insert runs in
    one transaction — any individual failure rolls back the batch.
    """

    def __init__(self, form: CreateBlocksBulkForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        page: Page = self.form.cleaned_data["page"]
        parent: Optional[Block] = self.form.cleaned_data.get("parent")
        blocks_in: List[Dict[str, Any]] = self.form.cleaned_data["blocks"]

        next_order = BlockRepository.get_max_order(page, parent) + 1
        created: List[Dict[str, Any]] = []

        with transaction.atomic():
            for i, item in enumerate(blocks_in):
                order = item.get("order")
                if order is None:
                    order = next_order + i

                form_data: Dict[str, Any] = {
                    "user": user.id,
                    "page": str(page.uuid),
                    "content": item["content"],
                    "block_type": item["block_type"],
                    "order": order,
                }
                if parent is not None:
                    form_data["parent"] = str(parent.uuid)

                inner = CreateBlockForm(form_data)
                if not inner.is_valid():
                    raise ValueError(
                        f"blocks[{i}] failed validation: {inner.errors.as_json()}"
                    )
                block = CreateBlockCommand(inner).execute()
                created.append(
                    {
                        "block_uuid": str(block.uuid),
                        "content": block.content,
                        "block_type": block.block_type,
                        "order": block.order,
                    }
                )

        return {
            "created_count": len(created),
            "page_uuid": str(page.uuid),
            "parent_uuid": str(parent.uuid) if parent else None,
            "blocks": created,
            "affected_page_uuids": [str(page.uuid)],
        }
