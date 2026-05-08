from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_saved_views_form import ListSavedViewsForm
from ..models import SavedView
from ..repositories import SavedViewRepository


class ListSavedViewsCommand(AbstractBaseCommand):
    """List the user's saved views (system + own)."""

    def __init__(self, form: ListSavedViewsForm) -> None:
        self.form = form

    def execute(self) -> List[SavedView]:
        super().execute()
        user = self.form.cleaned_data["user"]
        return list(SavedViewRepository.list_for_user(user))
