from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_recent_activity_form import GetRecentActivityForm
from ..repositories import BlockRepository, PageRepository

CONTENT_PREVIEW_LEN = 120


class GetRecentActivityCommand(AbstractBaseCommand):
    """Most-recently-edited blocks and/or pages across the user's
    notes. Useful for "what was I working on yesterday?" answers.
    Items are unified into a single chronological list keyed off
    modified_at desc.
    """

    def __init__(self, form: GetRecentActivityForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        kind: str = (
            self.form.cleaned_data.get("kind") or GetRecentActivityForm.KIND_BOTH
        )
        limit: int = self.form.cleaned_data.get("limit") or 20

        items: List[Dict[str, Any]] = []

        if kind in (
            GetRecentActivityForm.KIND_BLOCK,
            GetRecentActivityForm.KIND_BOTH,
        ):
            blocks = BlockRepository.get_recent_blocks(user, limit)
            for block in blocks:
                preview = (block.content or "").strip()
                if len(preview) > CONTENT_PREVIEW_LEN:
                    preview = preview[: CONTENT_PREVIEW_LEN - 3] + "..."
                items.append(
                    {
                        "kind": "block",
                        "uuid": str(block.uuid),
                        "label": preview,
                        "block_type": block.block_type,
                        "page_uuid": (str(block.page.uuid) if block.page else None),
                        "page_title": block.page.title if block.page else None,
                        "modified_at": block.modified_at.isoformat(),
                    }
                )

        if kind in (
            GetRecentActivityForm.KIND_PAGE,
            GetRecentActivityForm.KIND_BOTH,
        ):
            pages = PageRepository.get_recently_modified(user, limit)
            for page in pages:
                items.append(
                    {
                        "kind": "page",
                        "uuid": str(page.uuid),
                        "label": page.title,
                        "page_type": page.page_type,
                        "modified_at": page.modified_at.isoformat(),
                    }
                )

        # Merge and re-trim — without this 'both' would over-fetch each
        # side and the final list could exceed the requested limit.
        items.sort(key=lambda i: i["modified_at"], reverse=True)
        items = items[:limit]

        return {
            "kind": kind,
            "count": len(items),
            "results": items,
        }
