from datetime import timedelta
from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from ..repositories.block_repository import BlockRepository

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
        today = user.today()

        start_date = self.form.cleaned_data.get("start_date") or today
        end_date = self.form.cleaned_data.get("end_date")
        if end_date is None:
            end_date = start_date + timedelta(days=DEFAULT_RANGE_DAYS)
        if end_date < start_date:
            return {"error": "end_date must be on or after start_date"}

        limit = self.form.cleaned_data.get("limit") or 50

        blocks = BlockRepository.get_scheduled_in_range(
            user, start_date, end_date, limit
        )
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "count": len(blocks),
            "results": [b.as_summary() for b in blocks],
        }
