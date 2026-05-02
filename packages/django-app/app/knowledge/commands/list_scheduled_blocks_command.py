from datetime import timedelta
from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from ..repositories.block_repository import BlockRepository
from ._tool_helpers import summarize_block

DEFAULT_RANGE_DAYS = 30


class ListScheduledBlocksCommand(AbstractBaseCommand):
    """List the user's blocks with a scheduled_for date in the inclusive
    range. Defaults the start to today (user tz) and the end to start+30
    days when the caller doesn't supply explicit values.
    """

    def __init__(self, form: ListScheduledBlocksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        today = today_for_user(user)

        start_date = self.form.cleaned_data.get("start_date") or today
        end_date = self.form.cleaned_data.get("end_date")
        if end_date is None:
            end_date = start_date + timedelta(days=DEFAULT_RANGE_DAYS)
        if end_date < start_date:
            return {"error": "end_date must be on or after start_date"}

        limit = self.form.cleaned_data.get("limit") or 50

        blocks = list(
            BlockRepository.get_queryset()
            .filter(
                user=user,
                scheduled_for__gte=start_date,
                scheduled_for__lte=end_date,
            )
            .select_related("page")
            .prefetch_related("reminders")
            .order_by("scheduled_for", "order")[:limit]
        )
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "count": len(blocks),
            "results": [summarize_block(b) for b in blocks],
        }
