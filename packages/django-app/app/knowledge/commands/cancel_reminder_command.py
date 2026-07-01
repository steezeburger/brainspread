from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.cancel_reminder_form import CancelReminderForm
from ..models import Block, Reminder


class CancelReminderCommand(AbstractBaseCommand):
    """Cancel all of the block's pending reminders without clearing the
    block's due_at. Refuses (returns an error result) when the block has
    no pending reminders — there's nothing to cancel. Sent / failed /
    skipped reminders aren't touched.
    """

    def __init__(self, form: CancelReminderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        block: Block = self.form.cleaned_data["block"]

        pending: list[Reminder] = block.get_pending_reminders()
        if not pending:
            return {"error": "block has no pending reminder to cancel"}

        for reminder in pending:
            reminder.cancel()
        return {
            "cancelled": True,
            "cancelled_count": len(pending),
            "reminder_uuid": str(pending[0].uuid),
            "status": pending[0].status,
            "block_uuid": str(block.uuid),
            "affected_page_uuids": ([str(block.page.uuid)] if block.page else []),
        }
