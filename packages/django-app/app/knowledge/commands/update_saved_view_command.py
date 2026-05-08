from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.update_saved_view_form import UpdateSavedViewForm
from ..models import SavedView
from ..repositories import SavedViewRepository
from ..services import query_engine


class UpdateSavedViewCommand(AbstractBaseCommand):
    """Edit a user-owned SavedView. System views (``is_system=True``) are
    read-only — clone them first via the duplicate command if a user
    wants a tweak."""

    def __init__(self, form: UpdateSavedViewForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()

        user = self.form.cleaned_data["user"]
        view_uuid = str(self.form.cleaned_data["view_uuid"])

        view = SavedViewRepository.get_by_uuid(view_uuid, user=user)
        if not view:
            raise ValidationError("Saved view not found")
        if view.is_system:
            raise ValidationError(
                "System views are read-only — duplicate first to customize"
            )

        cleaned = self.form.cleaned_data
        updates = {}

        if "name" in cleaned:
            updates["name"] = cleaned["name"]
        if "description" in cleaned:
            updates["description"] = cleaned["description"] or ""
        if "slug" in cleaned and cleaned["slug"]:
            new_slug = cleaned["slug"]
            if new_slug != view.slug and SavedViewRepository.slug_taken(
                user=user, slug=new_slug, exclude_uuid=view_uuid
            ):
                raise ValidationError(f"You already have a view with slug '{new_slug}'")
            updates["slug"] = new_slug
        if "filter" in cleaned and cleaned["filter"] is not None:
            updates["filter"] = cleaned["filter"]
        if "sort" in cleaned and cleaned["sort"] is not None:
            updates["sort"] = cleaned["sort"]

        # Re-compile against the proposed filter/sort to catch broken
        # specs before they hit the DB. We pull the merged values so a
        # partial update still validates against whatever's about to be
        # persisted.
        merged_filter = updates.get("filter", view.filter)
        merged_sort = updates.get("sort", view.sort)
        try:
            query_engine.compile(merged_filter, user=user, sort=merged_sort)
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        if not updates:
            return view
        return SavedViewRepository.update(view, **updates)
