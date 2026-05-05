from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.cancel_reminder_form import CancelReminderForm
from ..models import Reminder


class CancelReminderCommand(AbstractBaseCommand):
    """Cancel a pending reminder without clearing the block's
    scheduled_for. Refuses to touch reminders that have already fired
    (sent / failed / skipped / cancelled).
    """

    def __init__(self, form: CancelReminderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        reminder: Reminder = self.form.cleaned_data["reminder"]

        if reminder.status != Reminder.STATUS_PENDING:
            return {
                "error": (
                    f"reminder is not pending (status: {reminder.status});"
                    " nothing to cancel"
                )
            }

        reminder.cancel()
        return {
            "cancelled": True,
            "reminder_uuid": str(reminder.uuid),
            "status": reminder.status,
            "block_uuid": str(reminder.block.uuid),
            "affected_page_uuids": (
                [str(reminder.block.page.uuid)] if reminder.block.page else []
            ),
        }
