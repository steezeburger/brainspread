import re
from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..forms.update_page_references_form import UpdatePageReferencesForm
from ..models import Block, Page
from .sync_block_tags_command import SyncBlockTagsCommand


class UpdatePageReferencesCommand(AbstractBaseCommand):
    """Command to update all references to a page when its title or slug changes"""

    def __init__(self, form: UpdatePageReferencesForm) -> None:
        super().__init__()
        self.form = form

    def execute(self) -> List[Block]:
        """Execute the command and return list of updated blocks"""
        page: Page = self.form.cleaned_data["page"]
        old_title: str = self.form.cleaned_data.get("old_title")
        old_slug: str = self.form.cleaned_data.get("old_slug")
        user = self.form.cleaned_data["user"]

        print("DEBUG: UpdatePageReferencesCommand executing")
        print(f"DEBUG: Page: {page.title} (slug: {page.slug})")
        print(f"DEBUG: Old title: {old_title}")
        print(f"DEBUG: Old slug: {old_slug}")
        print(f"DEBUG: User: {user}")

        updated_blocks = []

        # Update wiki-style links [[Old Title]] -> [[New Title]]
        if old_title and old_title != page.title:
            print(f"DEBUG: Updating wiki links from '{old_title}' to '{page.title}'")
            wiki_blocks = self._update_wiki_links(old_title, page.title, user)
            updated_blocks.extend(wiki_blocks)

        # Update hashtag references #old-slug -> #new-slug
        if old_slug and old_slug != page.slug:
            print(
                f"DEBUG: Updating hashtag references from '{old_slug}' to '{page.slug}'"
            )
            hashtag_blocks = self._update_hashtag_references(old_slug, page.slug, user)
            updated_blocks.extend(hashtag_blocks)

        # Re-sync tags for all updated blocks to maintain M2M relationships
        for block in updated_blocks:
            sync_form = SyncBlockTagsForm(
                data={
                    "block": str(block.uuid),
                    "content": block.content,
                    "user": user.id,
                }
            )
            if sync_form.is_valid():
                sync_command = SyncBlockTagsCommand(sync_form)
                sync_command.execute()

        return updated_blocks

    def _update_wiki_links(self, old_title: str, new_title: str, user) -> List[Block]:
        """Update all wiki-style links from [[old_title]] to [[new_title]]"""
        # Find blocks with the old wiki-link pattern
        old_pattern = r"\[\[" + re.escape(old_title) + r"\]\]"
        blocks_with_old_links = Block.objects.filter(
            content__iregex=old_pattern, user=user
        )

        updated_blocks = []
        for block in blocks_with_old_links:
            # Replace old wiki-links with new ones
            new_content = re.sub(
                old_pattern, f"[[{new_title}]]", block.content, flags=re.IGNORECASE
            )
            if new_content != block.content:
                block.content = new_content
                block.save()
                updated_blocks.append(block)

        return updated_blocks

    def _update_hashtag_references(
        self, old_slug: str, new_slug: str, user
    ) -> List[Block]:
        """Update all hashtag references from #old-slug to #new-slug"""
        # Find blocks with the old hashtag pattern. Negative lookbehind skips
        # `\#slug` so backslash-escaped hashtags aren't rewritten.
        old_hashtag_pattern = r"(?<!\\)#" + re.escape(old_slug) + r"(?=\s|$|[^\w-])"
        blocks_with_old_hashtags = Block.objects.filter(
            content__iregex=old_hashtag_pattern, user=user
        )

        print(f"DEBUG: Looking for pattern: {old_hashtag_pattern}")
        print(
            f"DEBUG: Found {blocks_with_old_hashtags.count()} blocks matching pattern"
        )

        updated_blocks = []
        for block in blocks_with_old_hashtags:
            print(f"DEBUG: Processing block {block.uuid}: '{block.content}'")
            # Replace old hashtags with new ones
            new_content = re.sub(
                old_hashtag_pattern, f"#{new_slug}", block.content, flags=re.IGNORECASE
            )
            print(f"DEBUG: New content would be: '{new_content}'")
            if new_content != block.content:
                print("DEBUG: Content changed, saving block")
                block.content = new_content
                block.save()
                updated_blocks.append(block)
            else:
                print("DEBUG: No change in content")

        print(f"DEBUG: Updated {len(updated_blocks)} blocks")
        return updated_blocks
