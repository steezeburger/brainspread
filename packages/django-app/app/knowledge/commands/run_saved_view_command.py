from typing import Any, Dict

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_saved_view_form import RunSavedViewForm
from ..repositories import BlockRepository, SavedViewRepository
from ..services import query_engine


class RunSavedViewCommand(AbstractBaseCommand):
    """Compile and execute a SavedView's filter, returning matched blocks.

    Returns ``{"view": <view dict>, "count": <int>, "results": [<block
    dict>], "truncated": <bool>}``. ``results`` is sized at ``limit + 1``
    internally so the caller can tell whether the view had more matches
    than fit in the limit (for "show more" affordances).
    """

    def __init__(self, form: RunSavedViewForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        limit = self.form.cleaned_data.get("limit") or 100
        view_uuid = self.form.cleaned_data.get("view_uuid")
        view_slug = self.form.cleaned_data.get("view_slug")

        view = (
            SavedViewRepository.get_by_uuid(str(view_uuid), user=user)
            if view_uuid
            else SavedViewRepository.get_by_slug(view_slug, user=user)
        )
        if not view:
            raise ValidationError("Saved view not found")

        try:
            compiled = query_engine.compile(view.filter, user=user, sort=view.sort)
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        # Fetch limit+1 so we can flag when there are more results than fit.
        rows = list(BlockRepository.run_compiled_query(user, compiled, limit=limit + 1))
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]

        return {
            "view": view.to_dict(),
            "count": len(rows),
            "results": [b.to_dict(include_page_context=True) for b in rows],
            "truncated": truncated,
        }
