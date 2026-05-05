from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
from ..repositories import BlockRepository, PageRepository


class TagBlocksCommand(AbstractBaseCommand):
    """Add a set of page tags to a set of blocks (M2M Block.pages).

    Idempotent — adding a tag that's already present is a no-op. Both
    blocks and pages must belong to the user; missing items are
    reported per-uuid and skipped, the rest still apply.
    """

    def __init__(self, form: TagBlocksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        return _apply_tag_op(self.form, add=True)


class UntagBlocksCommand(AbstractBaseCommand):
    """Remove a set of page tags from a set of blocks (M2M Block.pages).

    Idempotent — removing a tag that wasn't there is a no-op.
    """

    def __init__(self, form: UntagBlocksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        return _apply_tag_op(self.form, add=False)


def _apply_tag_op(form, *, add: bool) -> Dict[str, Any]:
    user = form.cleaned_data["user"]
    block_uuids: List[str] = form.cleaned_data["block_uuids"]
    page_uuids: List[str] = form.cleaned_data["page_uuids"]

    pages = []
    missing_pages: List[str] = []
    for page_uuid in page_uuids:
        page = PageRepository.get_by_uuid(page_uuid, user=user)
        if page is None:
            missing_pages.append(page_uuid)
        else:
            pages.append(page)

    updated_count = 0
    missing_blocks: List[str] = []
    affected_page_uuids: Set[str] = set()

    if pages:
        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    missing_blocks.append(block_uuid)
                    continue
                if add:
                    block.pages.add(*pages)
                else:
                    block.pages.remove(*pages)
                updated_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

    return {
        "updated_count": updated_count,
        "missing_blocks": missing_blocks,
        "missing_pages": missing_pages,
        "affected_page_uuids": sorted(affected_page_uuids),
    }
