from typing import List, Tuple

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.models import Block, Page
from knowledge.repositories import BlockRepository, PageRepository

from ..forms.get_page_with_blocks_form import GetPageWithBlocksForm


class GetPageWithBlocksCommand(AbstractBaseCommand):
    """Command to get a page with all its blocks"""

    def __init__(self, form: GetPageWithBlocksForm) -> None:
        self.form = form

    def execute(self) -> Tuple[Page, List[Block], List[Block], List[Block]]:
        """Return page, direct blocks, referenced blocks, and overdue blocks.

        Overdue blocks are only populated when the resolved page is today's
        daily note; on any other page the list is empty. Overdue is defined
        per issue #59: scheduled_for < today AND block_type in
        (todo, doing, later) AND completed_at IS NULL.
        """
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

        # Get referenced blocks (blocks from other pages that reference this page)
        # Look for blocks that have this page in their M2M tags relationship, but don't belong to this page
        referenced_blocks = (
            page.tagged_blocks.exclude(page=page)
            .select_related("user", "page")
            .prefetch_related("reminders")
        )

        # Overdue only renders on today's daily page. On any other view it's
        # empty — historical daily pages show themselves as they were, and
        # non-daily pages don't surface a calendar-driven section.
        # NOTE: this section is intentionally hard-coded for now. Issue #60
        # will generalize it into a SavedView so users can build their own
        # sections with the same query+display pattern.
        overdue_blocks: List[Block] = []
        if page.page_type == "daily" and page.date == today:
            overdue_blocks = list(BlockRepository.get_overdue_blocks(user, today))

        return page, list(direct_blocks), list(referenced_blocks), overdue_blocks
