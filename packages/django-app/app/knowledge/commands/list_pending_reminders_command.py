from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_pending_reminders_form import ListPendingRemindersForm
from ..models import Reminder


class ListPendingRemindersCommand(AbstractBaseCommand):
    """List the user's reminders that haven't fired yet, oldest first."""

    def __init__(self, form: ListPendingRemindersForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        limit = self.form.cleaned_data.get("limit") or 25

        reminders = list(
            Reminder.objects.filter(
                block__user=user,
                sent_at__isnull=True,
                status=Reminder.STATUS_PENDING,
            )
            .select_related("block", "block__page")
            .order_by("fire_at")[:limit]
        )
        results = []
        for reminder in reminders:
            entry = reminder.to_dict()
            block = reminder.block
            entry["block_content"] = block.content
            entry["block_type"] = block.block_type
            entry["page_title"] = block.page.title if block.page else None
            entry["page_uuid"] = str(block.page.uuid) if block.page else None
            results.append(entry)
        return {"count": len(results), "results": results}
