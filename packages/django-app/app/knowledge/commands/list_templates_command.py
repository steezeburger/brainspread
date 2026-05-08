from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_templates_form import ListTemplatesForm
from ..models import Page
from ..repositories import PageRepository


class ListTemplatesCommand(AbstractBaseCommand):
    """Return the user's template pages (issue #106). The left nav uses
    this to populate its Templates section so the user can pick one to
    instantiate a new page from."""

    def __init__(self, form: ListTemplatesForm) -> None:
        self.form = form

    def execute(self) -> List[Page]:
        super().execute()
        user = self.form.cleaned_data["user"]
        return list(PageRepository.get_user_templates(user))
