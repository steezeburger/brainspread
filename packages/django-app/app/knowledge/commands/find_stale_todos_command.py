from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List

import pytz
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.find_stale_todos_form import FindStaleTodosForm
from ..repositories.block_repository import BlockRepository


class FindStaleTodosCommand(AbstractBaseCommand):
    """Open TODO blocks (block_type='todo', no scheduled_for, not yet
    completed) that are older than `older_than_days`. Age is measured
    from the start of the cutoff day in the user's timezone so the
    threshold matches what the user sees.
    """

    def __init__(self, form: FindStaleTodosForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        older_than: int = self.form.cleaned_data.get("older_than_days") or 14
        limit: int = self.form.cleaned_data.get("limit") or 50

        today: date = user.today()
        cutoff_date: date = today - timedelta(days=older_than)
        cutoff_dt: datetime = (
            user.tz()
            .localize(datetime.combine(cutoff_date, time.min))
            .astimezone(pytz.UTC)
        )

        blocks = BlockRepository.get_stale_todos(user, cutoff_dt, limit)

        now_utc = timezone.now()
        results: List[Dict[str, Any]] = []
        for block in blocks:
            age_days = (now_utc - block.created_at).days
            preview = block.content or ""
            if len(preview) > 160:
                preview = preview[:157] + "..."
            results.append(
                {
                    "block_uuid": str(block.uuid),
                    "content_preview": preview,
                    "page_title": block.page.title if block.page else None,
                    "page_uuid": str(block.page.uuid) if block.page else None,
                    "page_slug": block.page.slug if block.page else None,
                    "age_days": age_days,
                    "created_at": block.created_at.isoformat(),
                }
            )
        return {
            "today": today.isoformat(),
            "older_than_days": older_than,
            "count": len(results),
            "results": results,
        }
