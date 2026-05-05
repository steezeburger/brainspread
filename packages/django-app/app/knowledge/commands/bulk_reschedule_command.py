from datetime import date, timedelta
from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_reschedule_form import BulkRescheduleForm
from ..models import Block, Reminder
from ..repositories import BlockRepository


class BulkRescheduleCommand(AbstractBaseCommand):
    """Move N blocks to the same `new_date`. Each block's pending
    reminder shifts by its own per-block delta so 'reminder time of
    day' is preserved across the move. Re-scheduling a block that
    didn't have a date before just sets its scheduled_for; reminders
    aren't created.
    """

    def __init__(self, form: BulkRescheduleForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]
        new_date: date = self.form.cleaned_data["new_date"]

        updated_count = 0
        missing: List[str] = []
        affected_page_uuids: Set[str] = set()

        with transaction.atomic():
            for block_uuid in block_uuids:
                block: Block | None = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    missing.append(block_uuid)
                    continue

                # Per-block delta lets us shift the pending reminder by
                # the same amount the date moved, preserving time-of-day.
                old_date = block.scheduled_for
                block.scheduled_for = new_date
                block.save(update_fields=["scheduled_for", "modified_at"])

                if old_date is not None:
                    delta = new_date - old_date
                    if delta != timedelta(0):
                        pending = block.reminders.filter(
                            sent_at__isnull=True, status=Reminder.STATUS_PENDING
                        )
                        for reminder in pending:
                            reminder.fire_at = reminder.fire_at + delta
                            reminder.save(update_fields=["fire_at", "modified_at"])

                updated_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

        return {
            "updated_count": updated_count,
            "missing": missing,
            "new_date": new_date.isoformat(),
            "affected_page_uuids": sorted(affected_page_uuids),
        }
