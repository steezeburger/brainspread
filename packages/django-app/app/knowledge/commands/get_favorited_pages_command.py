from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_favorited_pages_form import GetFavoritedPagesForm
from ..models import Page
from ..repositories import PageRepository


class GetFavoritedPagesCommand(AbstractBaseCommand):
    """Return the user's favorited pages, ordered by title."""

    def __init__(self, form: GetFavoritedPagesForm) -> None:
        self.form = form

    def execute(self) -> List[Page]:
        super().execute()

        user = self.form.cleaned_data["user"]
        return list(PageRepository.get_favorited(user))
