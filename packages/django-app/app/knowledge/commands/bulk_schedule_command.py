from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_schedule_form import BulkScheduleForm
from ..forms.schedule_block_form import ScheduleBlockForm
from ..models import Block
from ..repositories import BlockRepository
from .schedule_block_command import ScheduleBlockCommand


class BulkScheduleCommand(AbstractBaseCommand):
    """Set the same `new_date` on N blocks, optionally creating /
    replacing pending reminders on each.

    Reminder-mode (reminder_time supplied) routes each block through
    ScheduleBlockCommand so the existing replace-pending-reminder
    semantics apply uniformly. Date-only mode just sets scheduled_for
    and shifts each existing pending reminder by the per-block delta
    (preserving time-of-day).
    """

    def __init__(self, form: BulkScheduleForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]
        new_date: date = self.form.cleaned_data["new_date"]
        reminder_time: Optional[time] = self.form.cleaned_data.get("reminder_time")
        reminder_date: Optional[date] = self.form.cleaned_data.get("reminder_date")

        # Route mode is decided once for the whole batch — either everyone
        # gets a reminder set (replace semantics) or nobody does (preserve
        # existing reminders, shift fire_at).
        if reminder_time is not None:
            return self._execute_with_reminders(
                user=user,
                block_uuids=block_uuids,
                new_date=new_date,
                reminder_date=reminder_date or new_date,
                reminder_time=reminder_time,
            )
        return self._execute_date_only(
            user=user, block_uuids=block_uuids, new_date=new_date
        )

    @staticmethod
    def _execute_date_only(
        *, user, block_uuids: List[str], new_date: date
    ) -> Dict[str, Any]:
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
                        pending = block.get_pending_reminder()
                        if pending is not None:
                            pending.fire_at = pending.fire_at + delta
                            pending.save(update_fields=["fire_at", "modified_at"])

                updated_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

        return {
            "updated_count": updated_count,
            "missing": missing,
            "new_date": new_date.isoformat(),
            "reminder_set": False,
            "affected_page_uuids": sorted(affected_page_uuids),
        }

    @staticmethod
    def _execute_with_reminders(
        *,
        user,
        block_uuids: List[str],
        new_date: date,
        reminder_date: date,
        reminder_time: time,
    ) -> Dict[str, Any]:
        updated_count = 0
        missing: List[str] = []
        affected_page_uuids: Set[str] = set()
        reminder_iso = reminder_time.strftime("%H:%M")

        with transaction.atomic():
            for block_uuid in block_uuids:
                block: Block | None = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    missing.append(block_uuid)
                    continue

                inner = ScheduleBlockForm(
                    {
                        "user": user.id,
                        "block": str(block.uuid),
                        "scheduled_for": new_date.isoformat(),
                        "reminder_date": reminder_date.isoformat(),
                        "reminder_time": reminder_iso,
                    }
                )
                if not inner.is_valid():
                    missing.append(block_uuid)
                    continue
                ScheduleBlockCommand(inner).execute()
                updated_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

        return {
            "updated_count": updated_count,
            "missing": missing,
            "new_date": new_date.isoformat(),
            "reminder_set": True,
            "reminder_date": reminder_date.isoformat(),
            "reminder_time": reminder_iso,
            "affected_page_uuids": sorted(affected_page_uuids),
        }
