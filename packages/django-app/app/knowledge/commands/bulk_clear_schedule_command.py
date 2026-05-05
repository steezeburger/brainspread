from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_clear_schedule_form import BulkClearScheduleForm
from ..forms.schedule_block_form import ScheduleBlockForm
from ..repositories import BlockRepository
from .schedule_block_command import ScheduleBlockCommand


class BulkClearScheduleCommand(AbstractBaseCommand):
    """Drop scheduled_for AND any pending reminder on N blocks in one
    approval. Wraps ScheduleBlockCommand per block (which already
    handles "missing scheduled_for == clear" semantics) so the cascade
    behaviour stays in one place. Per-row failures are reported and
    don't roll back the rest.
    """

    def __init__(self, form: BulkClearScheduleForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]

        cleared_count = 0
        skipped: List[Dict[str, str]] = []
        affected_page_uuids: Set[str] = set()

        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    skipped.append({"block_uuid": block_uuid, "reason": "not found"})
                    continue
                if block.scheduled_for is None and block.get_pending_reminder() is None:
                    # Nothing to clear; surface as a no-op rather than a failure.
                    skipped.append(
                        {"block_uuid": block_uuid, "reason": "nothing to clear"}
                    )
                    continue
                inner = ScheduleBlockForm({"user": user.id, "block": str(block.uuid)})
                if not inner.is_valid():
                    skipped.append(
                        {
                            "block_uuid": block_uuid,
                            "reason": _first_form_error(inner),
                        }
                    )
                    continue
                updated = ScheduleBlockCommand(inner).execute()
                cleared_count += 1
                if updated.page is not None:
                    affected_page_uuids.add(str(updated.page.uuid))

        return {
            "cleared_count": cleared_count,
            "skipped": skipped,
            "affected_page_uuids": sorted(affected_page_uuids),
        }


def _first_form_error(form) -> str:
    errors = form.errors
    if not errors:
        return "validation failed"
    first_field, field_errors = next(iter(errors.items()))
    if field_errors:
        return f"{first_field}: {field_errors[0]}"
    return "validation failed"
