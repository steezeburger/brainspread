from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_cancel_reminders_form import BulkCancelRemindersForm
from ..repositories import BlockRepository


class BulkCancelRemindersCommand(AbstractBaseCommand):
    """Cancel the pending reminder on each block in the list. Blocks
    that have no pending reminder are skipped (reported, not errored).
    Blocks the user doesn't own end up in `not_found`.
    """

    def __init__(self, form: BulkCancelRemindersForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]

        cancelled_count = 0
        not_found: List[str] = []
        no_reminder: List[str] = []
        affected_page_uuids: Set[str] = set()

        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if block is None:
                    not_found.append(block_uuid)
                    continue
                pending = block.get_pending_reminder()
                if pending is None:
                    no_reminder.append(block_uuid)
                    continue
                pending.cancel()
                cancelled_count += 1
                if block.page is not None:
                    affected_page_uuids.add(str(block.page.uuid))

        return {
            "cancelled_count": cancelled_count,
            "not_found": not_found,
            "no_reminder": no_reminder,
            "affected_page_uuids": sorted(affected_page_uuids),
        }
