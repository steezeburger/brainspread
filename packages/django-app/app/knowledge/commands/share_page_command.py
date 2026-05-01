from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.share_page_form import SharePageForm
from ..models import Page
from ..models.page import SHARE_MODE_PRIVATE, generate_share_token


class SharePageCommand(AbstractBaseCommand):
    """Set a page's public share mode and ensure a stable share_token exists.

    The share_token is generated lazily on the first non-private mode and
    kept on the page even when the user flips back to private. This way a
    sender's existing link keeps working when they re-share later, matching
    Google Docs behavior.
    """

    def __init__(self, form: SharePageForm) -> None:
        self.form = form

    def execute(self) -> Page:
        super().execute()

        page = self.form.cleaned_data["page"]
        share_mode = self.form.cleaned_data["share_mode"]

        page.share_mode = share_mode
        if share_mode != SHARE_MODE_PRIVATE and not page.share_token:
            page.share_token = generate_share_token()

        page.save(update_fields=["share_mode", "share_token", "modified_at"])
        return page
