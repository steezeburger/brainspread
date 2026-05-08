from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.reorder_page_embedded_views_form import ReorderPageEmbeddedViewsForm
from ..repositories import PageEmbeddedViewRepository, PageRepository


class ReorderPageEmbeddedViewsCommand(AbstractBaseCommand):
    """Bulk-reorder all embeds on a page in one shot.

    Returns the page's embeds in their new order so the caller can
    refresh state without a follow-up GET.
    """

    def __init__(self, form: ReorderPageEmbeddedViewsForm) -> None:
        self.form = form

    def execute(self) -> QuerySet:
        super().execute()

        user = self.form.cleaned_data["user"]
        page_uuid = str(self.form.cleaned_data["page_uuid"])
        ordered_uuids = self.form.cleaned_data["ordered_uuids"]

        page = PageRepository.get_by_uuid(page_uuid)
        if not page or page.user_id != user.id:
            raise ValidationError("Page not found")

        PageEmbeddedViewRepository.reorder(page, ordered_uuids)
        return PageEmbeddedViewRepository.list_for_page(page)
