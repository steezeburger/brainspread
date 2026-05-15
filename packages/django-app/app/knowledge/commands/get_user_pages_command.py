from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_user_pages_form import GetUserPagesForm
from ..models import Page


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

        queryset = Page.objects.filter(user=user)
        if published_only:
            queryset = queryset.filter(is_published=True)
        if page_type:
            queryset = queryset.filter(page_type=page_type)

        pages = queryset[offset : offset + limit]
        total_count = queryset.count()

        return {
            "pages": list(pages),
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }
