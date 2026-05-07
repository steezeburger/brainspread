from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_saved_view_form import GetSavedViewForm
from ..models import SavedView
from ..repositories import SavedViewRepository


class GetSavedViewCommand(AbstractBaseCommand):
    """Fetch one of the user's views by uuid or slug."""

    def __init__(self, form: GetSavedViewForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()
        user = self.form.cleaned_data["user"]
        view_uuid = self.form.cleaned_data.get("view_uuid")
        view_slug = self.form.cleaned_data.get("view_slug")

        view = (
            SavedViewRepository.get_by_uuid(str(view_uuid), user=user)
            if view_uuid
            else SavedViewRepository.get_by_slug(view_slug, user=user)
        )
        if not view:
            raise ValidationError("Saved view not found")
        return view
