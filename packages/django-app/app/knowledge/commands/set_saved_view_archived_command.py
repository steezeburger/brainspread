from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_saved_view_archived_form import SetSavedViewArchivedForm
from ..models import SavedView


class SetSavedViewArchivedCommand(AbstractBaseCommand):
    """Toggle the archived flag on a saved view.

    Archived views drop out of the main saved-views list and the left-nav
    pinned section, but stay reachable from the list's archived section
    (and by direct slug URL). The pinned flag is left untouched so
    unarchiving restores the view exactly as it was — system views can be
    archived too, same per-user reasoning as pinning.
    """

    def __init__(self, form: SetSavedViewArchivedForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()

        view = self.form.cleaned_data["view"]
        archived = bool(self.form.cleaned_data.get("archived"))

        if view.archived == archived:
            return view

        view.archived = archived
        view.save(update_fields=["archived", "modified_at"])
        return view
