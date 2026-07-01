from datetime import timedelta
from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_snooze_form import BulkSnoozeForm
from ..repositories import BlockRepository
from ..services.due_dates import shift_due_days


class BulkSnoozeCommand(AbstractBaseCommand):
    """Push N blocks' schedules + pending reminders forward by the same
    days/hours. Same semantics as single snooze_block:
    - due_at shifts only by `days` (preserving local time-of-day / midnight)
    - pending reminder fire_at shifts by the full days+hours delta

    Blocks with no schedule AND no pending reminder are reported in
    `nothing_to_snooze` rather than failed — the model just learns the
    list was a partial fit.
    """

    def __init__(self, form: BulkSnoozeForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]
        days: int = self.form.cleaned_data["days"]
        hours: int = self.form.cleaned_data["hours"]

        snoozed_count = 0
        not_found: List[str] = []
        nothing_to_snooze: List[str] = []
        affected_page_uuids: Set[str] = set()

        reminder_delta = timedelta(days=days, hours=hours)
        tz = user.tz()

        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    not_found.append(block_uuid)
                    continue
                pending = block.get_pending_reminders()
                if block.due_at is None and not pending:
                    nothing_to_snooze.append(block_uuid)
                    continue

                if block.due_at is not None and days != 0:
                    block.due_at = shift_due_days(
                        block.due_at, block.due_at_has_time, days, tz
                    )
                    block.save(update_fields=["due_at", "modified_at"])

                for reminder in pending:
                    reminder.fire_at = reminder.fire_at + reminder_delta
                    reminder.save(update_fields=["fire_at", "modified_at"])

                snoozed_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

        return {
            "snoozed_count": snoozed_count,
            "not_found": not_found,
            "nothing_to_snooze": nothing_to_snooze,
            "days": days,
            "hours": hours,
            "affected_page_uuids": sorted(affected_page_uuids),
        }
