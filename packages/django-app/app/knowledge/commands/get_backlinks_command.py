from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_backlinks_form import GetBacklinksForm
from ..models import Block, Page

CONTENT_PREVIEW_LEN = 160


class GetBacklinksCommand(AbstractBaseCommand):
    """Return blocks that reference a page either via `[[Page Title]]`
    content links (Page.get_backlinks) or via the Block.pages M2M tag.
    The two sources are unioned, deduped by block uuid, and ordered by
    most-recently-modified.
    """

    def __init__(self, form: GetBacklinksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        page: Page = self.form.cleaned_data["page"]
        limit: int = self.form.cleaned_data.get("limit") or 50

        # Two sources, both already user-scoped:
        # - content backlinks: blocks whose content contains [[Title]]
        # - tag backlinks: blocks tagged with this page (M2M)
        # Union by id then re-fetch ordered + bounded so we don't blow
        # the limit on either source alone.
        content_ids = list(page.get_backlinks().values_list("id", flat=True))
        tag_ids = list(page.tagged_blocks.values_list("id", flat=True))
        all_ids = list(set(content_ids + tag_ids))

        blocks: List[Block] = list(
            Block.objects.filter(id__in=all_ids)
            .select_related("page")
            .order_by("-modified_at")[:limit]
        )

        results: List[Dict[str, Any]] = []
        for block in blocks:
            preview = block.content or ""
            if len(preview) > CONTENT_PREVIEW_LEN:
                preview = preview[: CONTENT_PREVIEW_LEN - 3] + "..."
            sources: List[str] = []
            if block.id in content_ids:
                sources.append("content_link")
            if block.id in tag_ids:
                sources.append("tag")
            results.append(
                {
                    "block_uuid": str(block.uuid),
                    "page_uuid": str(block.page.uuid) if block.page else None,
                    "page_title": block.page.title if block.page else None,
                    "page_slug": block.page.slug if block.page else None,
                    "content_preview": preview,
                    "block_type": block.block_type,
                    "sources": sources,
                }
            )

        return {
            "page_uuid": str(page.uuid),
            "page_title": page.title,
            "count": len(results),
            "results": results,
        }
