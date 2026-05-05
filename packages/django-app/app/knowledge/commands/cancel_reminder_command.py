from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.cancel_reminder_form import CancelReminderForm
from ..models import Block, Reminder


class CancelReminderCommand(AbstractBaseCommand):
    """Cancel the block's pending reminder without clearing the
    block's scheduled_for. Refuses (returns an error result) when
    the block has no pending reminder — there's nothing to cancel.
    Sent / failed / skipped reminders aren't touched.
    """

    def __init__(self, form: CancelReminderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        block: Block = self.form.cleaned_data["block"]

        pending: Reminder | None = block.reminders.filter(
            sent_at__isnull=True, status=Reminder.STATUS_PENDING
        ).first()
        if pending is None:
            return {"error": "block has no pending reminder to cancel"}

        pending.cancel()
        return {
            "cancelled": True,
            "reminder_uuid": str(pending.uuid),
            "status": pending.status,
            "block_uuid": str(block.uuid),
            "affected_page_uuids": ([str(block.page.uuid)] if block.page else []),
        }
