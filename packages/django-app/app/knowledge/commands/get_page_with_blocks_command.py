from typing import List, Tuple

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.models import Block, Page, PageEmbeddedView
from knowledge.repositories import (
    BlockRepository,
    PageEmbeddedViewRepository,
    PageRepository,
)

from ..forms.get_page_with_blocks_form import GetPageWithBlocksForm


class GetPageWithBlocksCommand(AbstractBaseCommand):
    """Command to get a page with all its blocks (and pinned embeds).

    Returns ``(page, direct_blocks, referenced_blocks, embedded_views)``.
    Embedded views are the saved-view widgets pinned above the bullet
    area — including the system ``overdue`` view for users who embed it,
    which replaced the old hard-coded Overdue section on today's daily.
    """

    def __init__(self, form: GetPageWithBlocksForm) -> None:
        self.form = form

    def execute(
        self,
    ) -> Tuple[Page, List[Block], List[Block], List[PageEmbeddedView]]:
        super().execute()

        user = self.form.cleaned_data.get("user")
        page = self.form.cleaned_data.get("page")
        date = self.form.cleaned_data.get("date")
        slug = self.form.cleaned_data.get("slug")

        today = user.today()

        if slug:
            # Get regular page by slug
            page = PageRepository.get_by_slug(slug, user)
            if not page:
                raise ValidationError(f"Page with slug '{slug}' not found")
        elif date:
            # Get or create daily note
            page, created = PageRepository.get_or_create_daily_note(user, date)
        elif not page:
            # Default to today's daily note (in the user's timezone).
            page, created = PageRepository.get_or_create_daily_note(user, today)

        # Get direct blocks (blocks that belong directly to this page)
        direct_blocks = BlockRepository.get_root_blocks(page)

        # Get referenced blocks (blocks from other pages that reference this
        # page via the M2M tag relationship). Descendants whose ancestor is
        # also tagged are dropped — they already render nested under that
        # ancestor's reference, so a standalone entry would just duplicate.
        referenced_blocks = BlockRepository.get_referenced_blocks(page)

        embedded_views = list(PageEmbeddedViewRepository.list_for_page(page))

        return (
            page,
            list(direct_blocks),
            list(referenced_blocks),
            embedded_views,
        )
