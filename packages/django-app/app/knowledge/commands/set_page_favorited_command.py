from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_page_favorited_form import SetPageFavoritedForm
from ..models import Page


class SetPageFavoritedCommand(AbstractBaseCommand):
    """Star or unstar a page so it appears in the left-nav Favorites section."""

    def __init__(self, form: SetPageFavoritedForm) -> None:
        self.form = form

    def execute(self) -> Page:
        super().execute()

        page = self.form.cleaned_data["page"]
        favorited = bool(self.form.cleaned_data.get("favorited"))

        page.favorited = favorited
        page.save(update_fields=["favorited", "modified_at"])
        return page
