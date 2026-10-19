import re
from typing import Optional

from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..constants import COMPLETED_TODO_TYPES
from ..forms.set_block_type_form import SetBlockTypeForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block, BlockRevision, Reminder
from ..repositories import BlockRevisionRepository
from ..services.state_prefix import (
    STATE_PREFIXES,
    ensure_state_prefix,
    strip_state_prefix,
)
from .touch_page_command import TouchPageCommand


class SetBlockTypeCommand(AbstractBaseCommand):
    """Set a block's block_type, maintaining completed_at and content prefix."""

    def __init__(self, form: SetBlockTypeForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]
        new_type: str = self.form.cleaned_data["block_type"]
        old_type = block.block_type

        if old_type == new_type:
            return block

        previous_snapshot = BlockRevisionRepository.snapshot(block)

        block.content = self._update_content_prefix(block.content, old_type, new_type)
        block.completed_at = self._next_completed_at(
            old_type, new_type, block.completed_at
        )
        block.block_type = new_type
        block.save()

        source = self.form.cleaned_data.get("source") or BlockRevision.SOURCE_USER
        BlockRevisionRepository.record_if_changed(block, previous_snapshot, source)

        # Once a block is completed, pending reminders are noise.
        # Stay-skipped on un-complete: user can reschedule manually. We set
        # sent_at alongside status because the block-level "pending reminder"
        # lookup (see Block._pending_reminder_local) keys off sent_at IS NULL.
        entering_completed = (
            new_type in COMPLETED_TODO_TYPES and old_type not in COMPLETED_TODO_TYPES
        )
        if entering_completed:
            now = timezone.now()
            Reminder.objects.filter(block=block, status=Reminder.STATUS_PENDING).update(
                status=Reminder.STATUS_SKIPPED,
                sent_at=now,
                modified_at=now,
            )

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return block

    @staticmethod
    def _next_completed_at(old_type: str, new_type: str, current):
        """Stamp completed_at on the way into a completed state, clear it
        on the way out, and leave it alone for any other transition."""
        was_completed = old_type in COMPLETED_TODO_TYPES
        is_completed = new_type in COMPLETED_TODO_TYPES
        if is_completed and not was_completed:
            return timezone.now()
        if was_completed and not is_completed:
            return None
        return current

    @staticmethod
    def _update_content_prefix(content: str, old_type: str, new_type: str) -> str:
        old_prefix = STATE_PREFIXES.get(old_type)
        new_prefix = STATE_PREFIXES.get(new_type)

        if old_prefix and new_prefix:
            content = _swap_prefix(content, old_prefix, new_prefix)
        elif new_prefix and not content.strip():
            return new_prefix
        elif old_prefix and not new_prefix:
            return strip_state_prefix(content, old_prefix)
        # Content that never carried the old keyword (blocks typed via
        # tools before issue #263) still has to end up with the new one.
        return ensure_state_prefix(content, new_type)


def _swap_prefix(content: str, old_prefix: str, new_prefix: str) -> str:
    # Replace case-insensitively, preserving surrounding whitespace/punctuation.
    content = re.sub(
        rf"\b{old_prefix}\b(?=\s*:)", new_prefix, content, flags=re.IGNORECASE
    )
    content = re.sub(
        rf"\b{old_prefix}\b(?!\s*:)", new_prefix, content, flags=re.IGNORECASE
    )
    return content


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
