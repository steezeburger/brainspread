from datetime import timedelta
from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.snooze_block_form import SnoozeBlockForm
from ..models import Block, Reminder


class SnoozeBlockCommand(AbstractBaseCommand):
    """Push a single block's schedule forward by days and/or hours.

    Date side (`scheduled_for`) only respects `days` since it's a date,
    not a datetime. Reminder side (the block's pending reminder, if
    any) shifts by the full days+hours timedelta. Refuses if the block
    has neither a scheduled_for nor a pending reminder — there's
    nothing to snooze.
    """

    def __init__(self, form: SnoozeBlockForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        days: int = self.form.cleaned_data["days"]
        hours: int = self.form.cleaned_data["hours"]

        pending: Reminder | None = block.get_pending_reminder()

        if block.scheduled_for is None and pending is None:
            return {"error": "block has no schedule to snooze"}

        update_fields: list[str] = []

        if block.scheduled_for is not None and days != 0:
            block.scheduled_for = block.scheduled_for + timedelta(days=days)
            update_fields.append("scheduled_for")

        if update_fields:
            update_fields.append("modified_at")
            block.save(update_fields=update_fields)

        new_fire_at: str | None = None
        if pending is not None:
            pending.fire_at = pending.fire_at + timedelta(days=days, hours=hours)
            pending.save(update_fields=["fire_at", "modified_at"])
            new_fire_at = pending.fire_at.isoformat()

        return {
            "snoozed": True,
            "block_uuid": str(block.uuid),
            "scheduled_for": (
                block.scheduled_for.isoformat() if block.scheduled_for else None
            ),
            "reminder_fire_at": new_fire_at,
            "affected_page_uuids": ([str(block.page.uuid)] if block.page else []),
        }
