from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_saved_view_form import CreateSavedViewForm
from ..models import SavedView
from ..repositories import SavedViewRepository
from ..services import query_engine


class CreateSavedViewCommand(AbstractBaseCommand):
    """Create a user-owned SavedView.

    The filter / sort spec is compiled once at create time as a
    syntax-check — predicate validity (unknown fields, bad ops) shouldn't
    wait until first run to surface. Compiles aren't free but they don't
    touch the DB, so this is cheap.
    """

    def __init__(self, form: CreateSavedViewForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()

        user = self.form.cleaned_data["user"]
        name = self.form.cleaned_data["name"]
        slug = self.form.cleaned_data["slug"]
        description = self.form.cleaned_data.get("description", "") or ""
        filter_spec = self.form.cleaned_data["filter"]
        sort = self.form.cleaned_data.get("sort") or []

        if not slug:
            raise ValidationError("slug is required (or supply a name to auto-slug)")

        if SavedViewRepository.slug_taken(user=user, slug=slug):
            raise ValidationError(f"You already have a view with slug '{slug}'")

        try:
            query_engine.compile(filter_spec, user=user, sort=sort)
        except query_engine.QueryEngineError as exc:
            raise ValidationError(str(exc)) from exc

        return SavedViewRepository.create(
            user=user,
            name=name,
            slug=slug,
            description=description,
            filter_spec=filter_spec,
            sort=sort,
            is_system=False,
        )
