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
        count_only = self.form.cleaned_data.get("count_only")
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
            compiled = query_engine.compile(
                view.filter,
                user=user,
                sort=view.sort,
                context_date=effective_context_date,
            )
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        # Collapsed embeds only need the header count — count limit+1
        # without serializing the rows so the count + truncation badge
        # match the full path, but a daily page full of collapsed embeds
        # stays cheap.
        if count_only:
            matched = BlockRepository.count_compiled_query(
                user, compiled, limit=limit + 1
            )
            truncated = matched > limit
            return {
                "view": view.to_dict(),
                "count": min(matched, limit),
                "results": [],
                "truncated": truncated,
            }

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
