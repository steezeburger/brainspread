import re
from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..models import Block, Page


class SyncBlockTagsCommand(AbstractBaseCommand):
    """Command to synchronize a block's tags based on hashtags in content"""

    def __init__(self, form: SyncBlockTagsForm) -> None:
        super().__init__()
        self.form = form

    def execute(self) -> None:
        """Execute the command"""
        block: Block = self.form.cleaned_data["block"]
        content: str = self.form.cleaned_data["content"]
        user = self.form.cleaned_data["user"]

        hashtags = self._extract_hashtags(content)

        if not hashtags:
            # Remove all tags if no hashtags found (exclude daily notes)
            tag_pages = block.pages.filter(
                slug__in=list(block.get_tag_names())
            ).exclude(page_type="daily")
            for tag_page in tag_pages:
                block.pages.remove(tag_page)
            return

        current_tag_names = set(block.get_tag_names())
        new_tag_names = set(hashtags)

        # Remove tags that are no longer in content (exclude daily notes)
        tags_to_remove = current_tag_names - new_tag_names
        if tags_to_remove:
            tag_pages_to_remove = Page.objects.filter(
                slug__in=list(tags_to_remove),
                user=user,
            ).exclude(page_type="daily")
            for tag_page in tag_pages_to_remove:
                block.pages.remove(tag_page)

        # Add new tags
        tags_to_add = new_tag_names - current_tag_names
        for tag_name in tags_to_add:
            tag_page = self._get_or_create_tag_page(tag_name, user)
            block.pages.add(tag_page)

    def _extract_hashtags(self, content: str) -> List[str]:
        """Extract hashtag names from content"""
        if not content:
            return []

        # Negative lookbehind skips `\#tag` so backslash-escaped hashtags
        # don't create page links.
        hashtag_pattern = r"(?<!\\)#([a-zA-Z0-9_-]+)"
        return re.findall(hashtag_pattern, content)

    def _get_or_create_tag_page(self, tag_name: str, user) -> Page:
        """Get or create a tag page for the given tag name"""
        # Look for existing page by slug
        try:
            tag_page = Page.objects.get(slug=tag_name, user=user)
        except Page.DoesNotExist:
            # Create new page with human-readable title
            human_title = tag_name.replace("-", " ").title()
            tag_page = Page.objects.create(
                title=human_title,
                slug=tag_name,
                user=user,
                is_published=True,
            )
        return tag_page
