from datetime import timedelta
from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_snooze_form import BulkSnoozeForm
from ..repositories import BlockRepository


class BulkSnoozeCommand(AbstractBaseCommand):
    """Push N blocks' schedules + pending reminders forward by the same
    days/hours. Same semantics as single snooze_block:
    - scheduled_for shifts only by `days` (it's a date)
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

        date_delta = timedelta(days=days)
        reminder_delta = timedelta(days=days, hours=hours)

        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    not_found.append(block_uuid)
                    continue
                pending = block.get_pending_reminder()
                if block.scheduled_for is None and pending is None:
                    nothing_to_snooze.append(block_uuid)
                    continue

                if block.scheduled_for is not None and days != 0:
                    block.scheduled_for = block.scheduled_for + date_delta
                    block.save(update_fields=["scheduled_for", "modified_at"])

                if pending is not None:
                    pending.fire_at = pending.fire_at + reminder_delta
                    pending.save(update_fields=["fire_at", "modified_at"])

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
