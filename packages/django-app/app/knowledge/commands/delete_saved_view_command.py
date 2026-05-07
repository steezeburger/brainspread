from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.delete_saved_view_form import DeleteSavedViewForm
from ..repositories import SavedViewRepository


class DeleteSavedViewCommand(AbstractBaseCommand):
    """Delete a user-owned SavedView. System views can't be deleted."""

    def __init__(self, form: DeleteSavedViewForm) -> None:
        self.form = form

    def execute(self) -> None:
        super().execute()

        user = self.form.cleaned_data["user"]
        view_uuid = str(self.form.cleaned_data["view_uuid"])

        view = SavedViewRepository.get_by_uuid(view_uuid, user=user)
        if not view:
            raise ValidationError("Saved view not found")
        if view.is_system:
            raise ValidationError("System views can't be deleted")

        SavedViewRepository.delete(view)
