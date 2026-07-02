from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_user_pages_form import GetUserPagesForm
from ..repositories.page_repository import PageRepository


class GetUserPagesCommand(AbstractBaseCommand):
    """Command to get user's pages"""

    def __init__(self, form: GetUserPagesForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        """Execute the command"""
        super().execute()  # This validates the form

        user = self.form.cleaned_data.get("user")
        published_only = self.form.cleaned_data.get("published_only", True)
        limit = self.form.cleaned_data.get("limit", 10)
        offset = self.form.cleaned_data.get("offset", 0)
        page_type = self.form.cleaned_data.get("page_type") or None
        # "modified" default keeps the page picker's empty-query landing
        # state surfacing what the user has been touching lately; the
        # All Pages surface passes "title" / "date" explicitly.
        order_by = self.form.cleaned_data.get("order_by") or "modified"

        return PageRepository.get_user_pages(
            user=user,
            published_only=published_only,
            limit=limit,
            offset=offset,
            page_type=page_type,
            order_by=order_by,
        )
