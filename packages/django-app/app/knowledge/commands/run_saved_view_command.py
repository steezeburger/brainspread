from typing import Any, Dict

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_saved_view_form import RunSavedViewForm
from ..repositories import SavedViewRepository
from ..services import query_engine
from ..services.view_execution import run_view


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
        context_date = self.form.cleaned_data.get("context_date")

        view = (
            SavedViewRepository.get_by_uuid(str(view_uuid), user=user)
            if view_uuid
            else SavedViewRepository.get_by_slug(view_slug, user=user)
        )
        if not view:
            raise ValidationError("Saved view not found")

        # Only honor ``context_date`` when the view opts in via
        # ``dates_relative_to_daily``. Without the gate a stray
        # ``context_date`` from a daily-page embed would rebase
        # date tokens on every view — defeating the explicit toggle
        # the user picked. When the toggle is off the engine falls
        # back to ``user.today()`` regardless of what the caller sent.
        effective_context_date = context_date if view.dates_relative_to_daily else None

        try:
            rows, truncated = run_view(
                user,
                view,
                limit=limit,
                context_date=effective_context_date,
            )
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        return {
            "view": view.to_dict(),
            "count": len(rows),
            "results": [b.to_dict(include_page_context=True) for b in rows],
            "truncated": truncated,
        }
