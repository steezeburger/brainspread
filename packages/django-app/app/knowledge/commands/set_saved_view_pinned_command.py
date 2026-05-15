from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_saved_view_pinned_form import SetSavedViewPinnedForm
from ..models import SavedView


class SetSavedViewPinnedCommand(AbstractBaseCommand):
    """Toggle the pinned flag on a saved view.

    Pinned views appear in the left-nav for quick access. System views
    can be pinned too — they're read-only for spec but the pin/unpin
    affordance is per-user and applies to any of the user's rows.
    """

    def __init__(self, form: SetSavedViewPinnedForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()

        view = self.form.cleaned_data["view"]
        pinned = bool(self.form.cleaned_data.get("pinned"))

        if view.pinned == pinned:
            return view

        view.pinned = pinned
        view.save(update_fields=["pinned", "modified_at"])
        return view
