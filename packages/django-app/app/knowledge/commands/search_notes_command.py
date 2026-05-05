from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.search_notes_form import SearchNotesForm
from ..repositories.block_repository import BlockRepository


class SearchNotesCommand(AbstractBaseCommand):
    """Substring search over the user's blocks for the assistant's
    search_notes tool. Returns block uuid, page title/slug, type, content.
    """

    def __init__(self, form: SearchNotesForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        query = self.form.cleaned_data["query"].strip()
        limit = self.form.cleaned_data.get("limit") or 10

        blocks = (
            BlockRepository.search_by_content(user, query)
            .select_related("page")
            .order_by("-modified_at")[:limit]
        )
        results: List[Dict[str, Any]] = [
            {
                "block_uuid": str(block.uuid),
                "page_title": block.page.title if block.page else None,
                "page_slug": block.page.slug if block.page else None,
                "block_type": block.block_type,
                "content": block.content,
            }
            for block in blocks
        ]
        return {"query": query, "count": len(results), "results": results}
