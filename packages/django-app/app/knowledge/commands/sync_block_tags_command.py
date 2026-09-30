import re
from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..models import Block
from ..repositories import PageRepository


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
        current_tag_names = set(block.get_tag_names())

        if not hashtags:
            # Remove all tags if no hashtags found (exclude daily notes).
            # block.pages.remove() below is a no-op for a page that isn't
            # actually attached, so matching by slug alone is enough.
            tag_pages = PageRepository.get_by_slugs(user, current_tag_names).exclude(
                page_type="daily"
            )
            for tag_page in tag_pages:
                block.pages.remove(tag_page)
            return

        new_tag_names = set(hashtags)

        # Remove tags that are no longer in content (exclude daily notes)
        tags_to_remove = current_tag_names - new_tag_names
        if tags_to_remove:
            tag_pages_to_remove = PageRepository.get_by_slugs(
                user, tags_to_remove
            ).exclude(page_type="daily")
            for tag_page in tag_pages_to_remove:
                block.pages.remove(tag_page)

        # Add new tags
        tags_to_add = new_tag_names - current_tag_names
        for tag_name in tags_to_add:
            tag_page = PageRepository.get_or_create_by_slug(user, tag_name)
            block.pages.add(tag_page)

    def _extract_hashtags(self, content: str) -> List[str]:
        """Extract hashtag names from content"""
        if not content:
            return []

        # Drop fenced code blocks and inline code spans before scanning so
        # `#foo` inside `` `code` `` or ```` ```...``` ```` doesn't create
        # tag pages. Mirrors the frontend rendering, which leaves hashtags
        # inside code untouched.
        cleaned = re.sub(r"```[^\n`]*\n[\s\S]*?```", "", content)
        cleaned = re.sub(r"`[^`\n]+`", "", cleaned)

        # Negative lookbehind skips `\#tag` so backslash-escaped hashtags
        # don't create page links.
        hashtag_pattern = r"(?<!\\)#([a-zA-Z0-9_-]+)"
        return re.findall(hashtag_pattern, cleaned)
