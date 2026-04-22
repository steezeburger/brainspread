import re

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.toggle_block_todo_form import ToggleBlockTodoForm
from ..models import Block


class ToggleBlockTodoCommand(AbstractBaseCommand):
    """Command to toggle a block's todo status"""

    def __init__(self, form: ToggleBlockTodoForm) -> None:
        self.form = form

    def execute(self) -> Block:
        """Execute the command"""
        super().execute()  # This validates the form

        block = self.form.cleaned_data["block"]

        # Cycle through todo states: bullet -> todo -> doing -> done -> later -> wontdo -> todo
        if block.block_type == "todo":
            block.block_type = "doing"
            block.content = self._replace_content_prefix(block.content, "TODO", "DOING")
        elif block.block_type == "doing":
            block.block_type = "done"
            block.content = self._replace_content_prefix(block.content, "DOING", "DONE")
        elif block.block_type == "done":
            block.block_type = "later"
            block.content = self._replace_content_prefix(block.content, "DONE", "LATER")
        elif block.block_type == "later":
            block.block_type = "wontdo"
            block.content = self._replace_content_prefix(
                block.content, "LATER", "WONTDO"
            )
        elif block.block_type == "wontdo":
            block.block_type = "todo"
            block.content = self._replace_content_prefix(
                block.content, "WONTDO", "TODO"
            )
        else:
            block.block_type = "todo"
            # For non-todo blocks, prepend TODO if content doesn't start with it
            if not re.match(r"^\s*todo\b", block.content, re.IGNORECASE):
                block.content = f"TODO {block.content}".strip()

        block.save()
        return block

    def _replace_content_prefix(
        self, content: str, old_prefix: str, new_prefix: str
    ) -> str:
        """Replace old prefix with new prefix in content, preserving case and formatting"""
        # Replace with colon (e.g., "TODO:" -> "DONE:")
        content = re.sub(rf"\b{old_prefix}\b(?=\s*:)", new_prefix, content)
        # Replace without colon (e.g., "TODO" -> "DONE")
        content = re.sub(rf"\b{old_prefix}\b(?!\s*:)", new_prefix, content)
        # Handle lowercase variants
        content = re.sub(
            rf"\b{old_prefix.lower()}\b(?=\s*:)",
            new_prefix,
            content,
            flags=re.IGNORECASE,
        )
        content = re.sub(
            rf"\b{old_prefix.lower()}\b(?!\s*:)",
            new_prefix,
            content,
            flags=re.IGNORECASE,
        )
        return content
