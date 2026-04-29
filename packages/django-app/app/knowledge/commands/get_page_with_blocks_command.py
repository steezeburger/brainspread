from typing import List, Tuple

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user
from knowledge.models import Block, Page
from knowledge.repositories import BlockRepository, PageRepository

from ..forms.get_page_with_blocks_form import GetPageWithBlocksForm


class GetPageWithBlocksCommand(AbstractBaseCommand):
    """Command to get a page with all its blocks"""

    def __init__(self, form: GetPageWithBlocksForm) -> None:
        self.form = form

    def execute(self) -> Tuple[Page, List[Block], List[Block]]:
        """Execute the command - returns page, direct blocks, and referenced blocks"""
        super().execute()

        user = self.form.cleaned_data.get("user")
        page = self.form.cleaned_data.get("page")
        date = self.form.cleaned_data.get("date")
        slug = self.form.cleaned_data.get("slug")

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
            page, created = PageRepository.get_or_create_daily_note(
                user, today_for_user(user)
            )

        # Get direct blocks (blocks that belong directly to this page)
        direct_blocks = BlockRepository.get_root_blocks(page)

        # Get referenced blocks (blocks from other pages that reference this page)
        # Look for blocks that have this page in their M2M tags relationship, but don't belong to this page
        referenced_blocks = page.tagged_blocks.exclude(page=page)

        return page, list(direct_blocks), list(referenced_blocks)
