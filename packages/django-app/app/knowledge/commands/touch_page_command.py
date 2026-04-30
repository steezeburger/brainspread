from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.touch_page_form import TouchPageForm
from ..models import Page


class TouchPageCommand(AbstractBaseCommand):
    """Bump a page's modified_at to the current time.

    Block-mutating commands call this so the page sorts to the top of the
    "recently modified" sidebar list whenever its blocks change. modified_at
    is auto_now=True, so saving with update_fields=["modified_at"] is enough
    to move the timestamp forward without touching any other column.
    """

    def __init__(self, form: TouchPageForm) -> None:
        self.form = form

    def execute(self) -> Page:
        super().execute()

        page = self.form.cleaned_data["page"]
        page.save(update_fields=["modified_at"])
        return page
