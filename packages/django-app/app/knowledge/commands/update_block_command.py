from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..forms.touch_page_form import TouchPageForm
from ..forms.update_block_form import UpdateBlockForm
from ..models import Block
from .sync_block_tags_command import SyncBlockTagsCommand
from .touch_page_command import TouchPageCommand


class UpdateBlockCommand(AbstractBaseCommand):
    """Command to update an existing block"""

    def __init__(self, form: UpdateBlockForm) -> None:
        self.form = form

    def execute(self) -> Block:
        """Execute the command"""
        super().execute()  # This validates the form

        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]

        # Update fields
        content_updated = False
        if "parent" in self.form.cleaned_data:
            parent = self.form.cleaned_data["parent"]
            # Check for circular references
            if self._would_create_circular_reference(block, parent):
                raise ValidationError(
                    "Cannot create circular reference: block cannot be its own ancestor"
                )

            block.parent = parent
        else:
            # If no parent is provided, ensure parent is set to None
            block.parent = None

        # Update other fields
        for field in [
            "content",
            "content_type",
            "block_type",
            "order",
            "media_url",
            "media_metadata",
            "properties",
            "collapsed",
        ]:
            if (
                field in self.form.cleaned_data
                and self.form.cleaned_data[field] is not None
            ):
                setattr(block, field, self.form.cleaned_data[field])
                if field == "content":
                    content_updated = True

        # asset is allowed to round-trip back to None (caller explicitly
        # detaching), so it gets its own branch instead of riding along
        # with the "is not None" filter above.
        if "asset" in self.form.cleaned_data:
            block.asset = self.form.cleaned_data["asset"]

        # Auto-detect block type from content if content was updated
        if content_updated:
            auto_detected_type = self._detect_block_type_from_content(
                block.content, block.block_type
            )
            if auto_detected_type != block.block_type:
                block.block_type = auto_detected_type

        block.save()

        # Extract and set tags if content was updated (business logic)
        # Skip for code blocks — their content is code, not markdown.
        if content_updated and block.content and block.block_type != "code":
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

        # Extract and set properties from content if content was updated (business logic)
        # Skip for code blocks — `key::value` inside code shouldn't be parsed.
        if content_updated and block.content and block.block_type != "code":
            block.extract_properties_from_content()

        # Bump the page's modified_at so the recent-pages sidebar reflects
        # this edit even though only the block row changed.
        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return block

    def _detect_block_type_from_content(
        self, content: str, current_block_type: str
    ) -> str:
        """Auto-detect block type from content patterns"""
        # Auto-detect promotes bullet/todo/doing toward a more specific
        # state when their content carries a recognizable prefix. We do NOT
        # auto-detect for done/later/wontdo — those are explicit terminal
        # states the user opted into via the bullet, and a content save
        # (e.g. an unrelated edit, mobile autocorrect mangling the "DONE"
        # prefix, or simply the user removing the prefix while typing)
        # shouldn't silently downgrade them back to a plain bullet.
        if current_block_type not in ["bullet", "todo", "doing"]:
            return current_block_type

        # Only auto-detect if we have content
        if not content:
            return current_block_type

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
        elif content_lower.startswith("doing"):
            return "doing"
        elif content_lower.startswith("done"):
            return "done"
        elif content_lower.startswith("later"):
            return "later"
        elif content_lower.startswith("wontdo"):
            return "wontdo"

        # No pattern matched: only downgrade todo/doing back to bullet.
        # bullet stays bullet; done/later/wontdo were already filtered out
        # at the top of the method.
        if current_block_type in ["todo", "doing"]:
            return "bullet"
        return current_block_type

    def _would_create_circular_reference(self, block, proposed_parent):
        """Check if setting proposed_parent as parent would create a circular reference"""
        # Walk up the proposed parent's ancestry to see if we find the block itself
        current = proposed_parent
        while current:
            if current.uuid == block.uuid:
                return True
            current = current.parent
        return False
