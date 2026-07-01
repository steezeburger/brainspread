from datetime import timedelta
from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.snooze_block_form import SnoozeBlockForm
from ..models import Block, Reminder
from ..services.due_dates import shift_due_days


class SnoozeBlockCommand(AbstractBaseCommand):
    """Push a single block's due date forward by days and/or hours.

    Due side (`due_at`) only respects `days`: for an all-day item the local
    date moves and midnight is preserved; for a timed item the day moves and
    the local time-of-day is preserved (DST-safe). Reminder side (the block's
    pending reminder, if any) shifts by the full days+hours timedelta. Refuses
    if the block has neither a due_at nor a pending reminder — nothing to
    snooze.
    """

    def __init__(self, form: SnoozeBlockForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        days: int = self.form.cleaned_data["days"]
        hours: int = self.form.cleaned_data["hours"]

        pending: list[Reminder] = block.get_pending_reminders()

        if block.due_at is None and not pending:
            return {"error": "block has no schedule to snooze"}

        update_fields: list[str] = []

        if block.due_at is not None and days != 0:
            block.due_at = shift_due_days(
                block.due_at, block.due_at_has_time, days, block.user.tz()
            )
            update_fields.append("due_at")

        if update_fields:
            update_fields.append("modified_at")
            block.save(update_fields=update_fields)

        # Every pending reminder shifts by the same delta so their
        # relative spacing (e.g. a nudge series) is preserved.
        new_fire_at: str | None = None
        delta = timedelta(days=days, hours=hours)
        for reminder in pending:
            reminder.fire_at = reminder.fire_at + delta
            reminder.save(update_fields=["fire_at", "modified_at"])
        if pending:
            new_fire_at = pending[0].fire_at.isoformat()

        return {
            "snoozed": True,
            "block_uuid": str(block.uuid),
            "due_at": (block.due_at.isoformat() if block.due_at else None),
            "due_date": block._due_local_date(),
            "reminder_fire_at": new_fire_at,
            "affected_page_uuids": ([str(block.page.uuid)] if block.page else []),
        }
