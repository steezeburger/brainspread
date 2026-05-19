from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_page_embedded_view_form import CreatePageEmbeddedViewForm
from ..models import PageEmbeddedView
from ..models.page_embedded_view import SCOPE_DAILY, SCOPE_PAGE
from ..repositories import (
    PageEmbeddedViewRepository,
    PageRepository,
    SavedViewRepository,
)


class CreatePageEmbeddedViewCommand(AbstractBaseCommand):
    """Embed a SavedView on a Page.

    On a daily page the embed is stored daily-scoped (``scope='daily'``,
    no page FK) so it follows the daily-page concept and renders on
    whichever daily the user opens — not just the date that was current
    when they clicked Embed. On any other page type the embed is tied
    to the specific page.

    Idempotent within its scope bucket: re-embedding the same view on
    any daily returns the existing daily-scoped row; re-embedding on a
    specific page returns the existing per-page row.
    """

    def __init__(self, form: CreatePageEmbeddedViewForm) -> None:
        self.form = form

    def execute(self) -> PageEmbeddedView:
        super().execute()

        user = self.form.cleaned_data["user"]
        page_uuid = str(self.form.cleaned_data["page_uuid"])
        saved_view_uuid = str(self.form.cleaned_data["saved_view_uuid"])

        page = PageRepository.get_by_uuid(page_uuid)
        if not page or page.user_id != user.id:
            raise ValidationError("Page not found")

        view = SavedViewRepository.get_by_uuid(saved_view_uuid, user=user)
        if not view:
            raise ValidationError("Saved view not found")

        existing = PageEmbeddedViewRepository.get_for_page_and_view(page, view)
        if existing is not None:
            return existing

        is_daily = page.page_type == "daily"
        next_order = PageEmbeddedViewRepository.next_order_for_page(page)
        return PageEmbeddedViewRepository.create(
            user=user,
            page=None if is_daily else page,
            saved_view=view,
            order=next_order,
            scope=SCOPE_DAILY if is_daily else SCOPE_PAGE,
        )
