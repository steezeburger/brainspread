from django.utils.text import slugify

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_page_form import CreatePageForm
from ..models import Page


class CreatePageCommand(AbstractBaseCommand):
    """Command to create a new page"""

    def __init__(self, form: CreatePageForm) -> None:
        self.form = form

    def execute(self) -> Page:
        """Execute the command"""
        super().execute()  # This validates the form

        user = self.form.cleaned_data["user"]
        title = self.form.cleaned_data["title"]

        page = Page.objects.create(
            user=user,
            title=title,
            slug=self.form.cleaned_data.get("slug") or slugify(title),
            is_published=self.form.cleaned_data.get("is_published", True),
            page_type=self.form.cleaned_data.get("page_type") or "page",
        )

        return page
