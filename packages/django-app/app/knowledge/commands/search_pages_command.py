from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.search_pages_form import SearchPagesForm
from ..models import PagesData
from ..repositories import PageRepository


class SearchPagesCommand(AbstractBaseCommand):
    """Command to search user's pages by title and slug"""

    def __init__(self, form: SearchPagesForm) -> None:
        self.form = form

    def execute(self) -> PagesData:
        """Execute the search command"""
        super().execute()  # This validates the form

        user = self.form.cleaned_data.get("user")
        query = self.form.cleaned_data.get("query")
        limit = self.form.cleaned_data.get("limit", 10)
        page_type = self.form.cleaned_data.get("page_type") or None

        queryset = PageRepository.search(user, query, page_type=page_type)
        pages = list(queryset[:limit])

        return PagesData(
            pages=[page.to_dict() for page in pages],
            total_count=queryset.count(),
            has_more=False,
        )
