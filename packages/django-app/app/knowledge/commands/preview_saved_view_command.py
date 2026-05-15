from typing import Any, Dict

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.preview_saved_view_form import PreviewSavedViewForm
from ..repositories import BlockRepository
from ..services import query_engine


class PreviewSavedViewCommand(AbstractBaseCommand):
    """Run an ad-hoc filter + sort spec without persisting it.

    Mirrors RunSavedViewCommand's response shape so the editor's Run
    button can reuse the same UI whether it's running a saved view or
    previewing an unsaved draft. The whole point: when a user is mid-
    edit, clicking Run should show results for what they've typed, not
    for the spec already on disk.
    """

    def __init__(self, form: PreviewSavedViewForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        filter_spec = self.form.cleaned_data["filter"]
        sort = self.form.cleaned_data.get("sort") or []
        limit = self.form.cleaned_data.get("limit") or 100

        try:
            compiled = query_engine.compile(filter_spec, user=user, sort=sort)
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        rows = list(BlockRepository.run_compiled_query(user, compiled, limit=limit + 1))
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]

        return {
            "count": len(rows),
            "results": [b.to_dict(include_page_context=True) for b in rows],
            "truncated": truncated,
        }
