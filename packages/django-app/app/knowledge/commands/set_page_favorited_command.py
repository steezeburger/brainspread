from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_page_favorited_form import SetPageFavoritedForm
from ..models import Page
from ..repositories import PageRepository


class SetPageFavoritedCommand(AbstractBaseCommand):
    """Star or unstar a page so it appears in the left-nav Favorites section."""

    def __init__(self, form: SetPageFavoritedForm) -> None:
        self.form = form

    def execute(self) -> Page:
        super().execute()

        page = self.form.cleaned_data["page"]
        favorited = bool(self.form.cleaned_data.get("favorited"))

        update_fields = ["favorited", "modified_at"]
        if favorited and not page.favorited:
            # Land newly favorited pages at the bottom of the list so the
            # user's existing drag-sorted order isn't disturbed.
            page.favorite_position = PageRepository.next_favorite_position(page.user)
            update_fields.append("favorite_position")
        page.favorited = favorited
        page.save(update_fields=update_fields)
        return page
