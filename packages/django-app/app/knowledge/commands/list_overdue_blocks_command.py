from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.list_overdue_blocks_form import ListOverdueBlocksForm
from ..repositories.block_repository import BlockRepository
from ._tool_helpers import summarize_block


class ListOverdueBlocksCommand(AbstractBaseCommand):
    """List the user's overdue scheduled blocks (todo / doing / later
    with scheduled_for before today in their timezone). Same predicate
    that drives the daily-page overdue section.
    """

    def __init__(self, form: ListOverdueBlocksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        limit = self.form.cleaned_data.get("limit") or 25

        today = today_for_user(user)
        blocks = list(BlockRepository.get_overdue_blocks(user, today)[:limit])
        return {
            "today": today.isoformat(),
            "count": len(blocks),
            "results": [summarize_block(b) for b in blocks],
        }
