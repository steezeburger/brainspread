from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_page_embedded_view_form import CreatePageEmbeddedViewForm
from ..models import PageEmbeddedView
from ..repositories import (
    PageEmbeddedViewRepository,
    PageRepository,
    SavedViewRepository,
)


class CreatePageEmbeddedViewCommand(AbstractBaseCommand):
    """Embed a SavedView on a Page.

    Idempotent on (page, saved_view) — if an embed already exists for
    that pair, the existing one is returned (the API is "ensure
    embedded," not "always create"). Both the page and the saved view
    must belong to the requesting user; cross-user UUID guesses raise
    ValidationError, never IntegrityError.
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

        next_order = PageEmbeddedViewRepository.next_order_for_page(page)
        return PageEmbeddedViewRepository.create(
            user=user,
            page=page,
            saved_view=view,
            order=next_order,
        )
