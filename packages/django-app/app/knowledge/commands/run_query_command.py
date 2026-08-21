from typing import Any, Dict, List

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_query_form import RunQueryForm
from ..services import query_engine
from ..services.view_execution import run_filter

DEFAULT_LIMIT = 25


class RunQueryCommand(AbstractBaseCommand):
    """Run an ad-hoc structured query for the AI tools (issue #78).

    The single search/filter surface the assistant composes against —
    everything the query engine can select (tags, types, due/completed
    ranges, properties, content), one tool. Replaces the content-only
    search_notes tool; a plain text search is just ``content:"..."``.

    Result rows keep the old search_notes shape (block_uuid, page_title,
    page_slug, block_type, content) plus due/completed timestamps so the
    model can reason about schedule queries without a follow-up fetch.
    """

    def __init__(self, form: RunQueryForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        filter_spec = self.form.cleaned_data["filter"]
        sort = self.form.cleaned_data.get("sort")
        limit = self.form.cleaned_data.get("limit") or DEFAULT_LIMIT

        try:
            blocks, truncated = run_filter(user, filter_spec, limit=limit, sort=sort)
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        results: List[Dict[str, Any]] = [
            {
                "block_uuid": str(block.uuid),
                "page_title": block.page.title if block.page else None,
                "page_slug": block.page.slug if block.page else None,
                "block_type": block.block_type,
                "content": block.content,
                "due_at": block.due_at.isoformat() if block.due_at else None,
                "completed_at": (
                    block.completed_at.isoformat() if block.completed_at else None
                ),
            }
            for block in blocks
        ]
        return {"count": len(results), "results": results, "truncated": truncated}
