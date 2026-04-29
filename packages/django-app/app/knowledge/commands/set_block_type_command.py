import re
from typing import Optional

from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_block_type_form import SetBlockTypeForm
from ..models import Block

# Block types that carry a leading content prefix (e.g. "TODO write docs").
STATE_PREFIXES = {
    "todo": "TODO",
    "doing": "DOING",
    "done": "DONE",
    "later": "LATER",
    "wontdo": "WONTDO",
}

# Terminal states — entering these sets completed_at; leaving clears it.
COMPLETED_TYPES = {"done", "wontdo"}


class SetBlockTypeCommand(AbstractBaseCommand):
    """Set a block's block_type, maintaining completed_at and content prefix."""

    def __init__(self, form: SetBlockTypeForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        new_type: str = self.form.cleaned_data["block_type"]
        old_type = block.block_type

        if old_type == new_type:
            return block

        block.content = self._update_content_prefix(block.content, old_type, new_type)
        block.completed_at = self._next_completed_at(
            old_type, new_type, block.completed_at
        )
        block.block_type = new_type
        block.save()
        return block

    @staticmethod
    def _next_completed_at(old_type: str, new_type: str, current):
        entering = new_type in COMPLETED_TYPES and old_type not in COMPLETED_TYPES
        leaving = old_type in COMPLETED_TYPES and new_type not in COMPLETED_TYPES
        if entering:
            return timezone.now()
        if leaving:
            return None
        return current

    @staticmethod
    def _update_content_prefix(content: str, old_type: str, new_type: str) -> str:
        old_prefix = STATE_PREFIXES.get(old_type)
        new_prefix = STATE_PREFIXES.get(new_type)

        if old_prefix and new_prefix:
            return _swap_prefix(content, old_prefix, new_prefix)
        if not old_prefix and new_prefix:
            return _prepend_prefix(content, new_prefix)
        if old_prefix and not new_prefix:
            return _strip_prefix(content, old_prefix)
        return content


def _swap_prefix(content: str, old_prefix: str, new_prefix: str) -> str:
    # Replace case-insensitively, preserving surrounding whitespace/punctuation.
    content = re.sub(
        rf"\b{old_prefix}\b(?=\s*:)", new_prefix, content, flags=re.IGNORECASE
    )
    content = re.sub(
        rf"\b{old_prefix}\b(?!\s*:)", new_prefix, content, flags=re.IGNORECASE
    )
    return content


def _prepend_prefix(content: str, new_prefix: str) -> str:
    if re.match(rf"^\s*{new_prefix}\b", content, re.IGNORECASE):
        return content
    return f"{new_prefix} {content}".strip()


def _strip_prefix(content: str, old_prefix: str) -> str:
    stripped = re.sub(
        rf"^\s*{old_prefix}\b\s*:?\s*", "", content, count=1, flags=re.IGNORECASE
    )
    return stripped


def get_next_todo_type(current_type: str) -> Optional[str]:
    """Return the next block_type in the todo cycle, or "todo" for non-todo blocks.

    bullet/other -> todo -> doing -> done -> later -> wontdo -> todo
    """
    cycle = {
        "todo": "doing",
        "doing": "done",
        "done": "later",
        "later": "wontdo",
        "wontdo": "todo",
    }
    return cycle.get(current_type, "todo")
