from datetime import datetime, time, timedelta
from typing import Any, Dict

import pytz
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.find_stale_todos_form import FindStaleTodosForm
from ..models import Block
from ._tool_helpers import user_tz


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
        older_than = self.form.cleaned_data.get("older_than_days") or 14
        limit = self.form.cleaned_data.get("limit") or 50

        today = today_for_user(user)
        cutoff_date = today - timedelta(days=older_than)
        tz = user_tz(user)
        cutoff_dt = tz.localize(datetime.combine(cutoff_date, time.min)).astimezone(
            pytz.UTC
        )

        blocks = list(
            Block.objects.filter(
                user=user,
                block_type="todo",
                scheduled_for__isnull=True,
                completed_at__isnull=True,
                created_at__lt=cutoff_dt,
            )
            .select_related("page")
            .order_by("created_at")[:limit]
        )

        now_utc = timezone.now()
        results = []
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
