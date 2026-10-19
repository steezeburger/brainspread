from typing import Any, Dict, List, Optional, Set

from django.core.exceptions import ValidationError
from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand
from core.models import User

from ..forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
from ..forms.update_block_form import UpdateBlockForm
from ..models import Block, Page
from ..repositories import BlockRepository, PageRepository
from ..services.tag_content import (
    TAGGABLE_SLUG_RE,
    append_tags,
    remove_tags,
)
from .update_block_command import UpdateBlockCommand


class TagBlocksCommand(AbstractBaseCommand):
    """Add a set of page tags to a set of blocks.

    Tags go into the content as ``#slug`` (issue #261) so they show on
    the block and survive later edits; the content save syncs the
    Block.pages links. Idempotent — adding a tag that's already present
    is a no-op. Both blocks and pages must belong to the user; missing
    items are reported per-uuid and skipped, the rest still apply.
    """

    def __init__(self, form: TagBlocksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        return _apply_tag_op(self.form, add=True)


class UntagBlocksCommand(AbstractBaseCommand):
    """Remove a set of page tags from a set of blocks — strips the
    ``#slug`` from content, which drops the link on re-sync.

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
    source: Optional[str] = form.cleaned_data.get("source")

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
                _rewrite_tag_content(block, pages, add=add, user=user, source=source)
                # Covers what content can't carry: code blocks and slugs
                # the hashtag parser can't read back.
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


def _rewrite_tag_content(
    block: Block,
    pages: List[Page],
    *,
    add: bool,
    user: User,
    source: Optional[str],
) -> None:
    if block.block_type == "code":
        return
    slugs = [p.slug for p in pages if TAGGABLE_SLUG_RE.match(p.slug)]
    content = block.content or ""
    new_content = append_tags(content, slugs) if add else remove_tags(content, slugs)
    if new_content == content:
        return

    data: Dict[str, Any] = {
        "user": user.id,
        "block": str(block.uuid),
        "content": new_content,
        # Explicit type so a todo whose content lacks its keyword isn't
        # auto-detected down to a bullet by this edit.
        "block_type": block.block_type,
    }
    if source:
        data["source"] = source
    update_form = UpdateBlockForm(data=data)
    if not update_form.is_valid():
        raise ValidationError(update_form.errors.as_json())
    UpdateBlockCommand(update_form).execute()
    block.refresh_from_db()
