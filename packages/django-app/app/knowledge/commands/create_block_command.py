from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_block_form import CreateBlockForm
from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block
from .sync_block_tags_command import SyncBlockTagsCommand
from .touch_page_command import TouchPageCommand


class CreateBlockCommand(AbstractBaseCommand):
    """Command to create a new block"""

    def __init__(self, form: CreateBlockForm) -> None:
        self.form = form

    def execute(self) -> Block:
        """Execute the command"""
        super().execute()  # This validates the form

        user = self.form.cleaned_data["user"]
        page = self.form.cleaned_data["page"]
        content = self.form.cleaned_data.get("content", "")
        content_type = self.form.cleaned_data.get("content_type", "text")
        block_type = self.form.cleaned_data.get("block_type", "bullet")
        order = self.form.cleaned_data.get("order", 0)
        parent = None
        if "parent" in self.form.cleaned_data:
            parent = self.form.cleaned_data.get("parent")
        media_url = self.form.cleaned_data.get("media_url", "")
        media_metadata = self.form.cleaned_data.get("media_metadata", {})
        properties = self.form.cleaned_data.get("properties", {})
        asset = self.form.cleaned_data.get("asset")
        query_view = self.form.cleaned_data.get("query_view")

        # Auto-detect block type from content if not explicitly set
        final_block_type = self._detect_block_type_from_content(content, block_type)

        # Create the block
        block = Block.objects.create(
            user=user,
            page=page,
            parent=parent,
            content=content,
            content_type=content_type,
            block_type=final_block_type,
            order=order,
            media_url=media_url,
            media_metadata=media_metadata,
            properties=properties,
            asset=asset,
            query_view=query_view,
        )

        # Extract and set tags from content (business logic)
        # Skip for code blocks — their content is code, not markdown.
        if block.content and block.block_type != "code":
            sync_tags_form = SyncBlockTagsForm(
                {
                    "block": block.uuid,
                    "content": block.content,
                    "user": user.id,
                }
            )
            if sync_tags_form.is_valid():
                sync_command = SyncBlockTagsCommand(sync_tags_form)
                sync_command.execute()
                # Refresh block from database to get updated tag relationships
                block.refresh_from_db()

        # Extract and set properties from content (business logic)
        # Skip for code blocks — `key::value` inside code shouldn't be parsed.
        if block.content and block.block_type != "code":
            block.extract_properties_from_content()

        # Bump the page's modified_at so it sorts to the top of the recent
        # pages list — adding a block counts as activity on the page.
        touch_form = TouchPageForm(data={"user": user.id, "page": str(page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return block

    def _detect_block_type_from_content(self, content: str, block_type: str) -> str:
        """Auto-detect block type from content patterns"""
        # If block_type was explicitly provided and isn't default, use it
        if block_type != "bullet":
            return block_type

        # Only auto-detect if we have content
        if not content:
            return block_type

        content_stripped = content.strip()
        content_lower = content_stripped.lower()

        # Check for TODO patterns
        if content_lower.startswith("todo"):
            return "todo"
        elif content_lower.startswith("[ ]"):
            return "todo"
        elif content_lower.startswith("[x]"):
            return "done"
        elif content_stripped.startswith("☐"):
            return "todo"
        elif content_stripped.startswith("☑"):
            return "done"

        # Default to original block_type
        return block_type
