from datetime import datetime, time, timedelta
from typing import Any, Dict, List

import pytz

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_completion_stats_form import GetCompletionStatsForm
from ..repositories.block_repository import BlockRepository

MAX_RANGE_DAYS = 366
OPEN_TODO_TYPES = ("todo", "doing", "later")


class GetCompletionStatsCommand(AbstractBaseCommand):
    """Counts of block types over a date range (done/wontdo by
    completed_at, todo/doing/later by created_at) plus a per-day done
    breakdown. All bucketing happens in the user's timezone.
    """

    def __init__(self, form: GetCompletionStatsForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        start_date = self.form.cleaned_data["start_date"]
        end_date = self.form.cleaned_data["end_date"]

        if end_date < start_date:
            return {"error": "end_date must be on or after start_date"}
        span_days = (end_date - start_date).days + 1
        if span_days > MAX_RANGE_DAYS:
            return {
                "error": f"range too large ({span_days} days); max {MAX_RANGE_DAYS}"
            }

        tz = user.tz()
        # Convert the user-local day boundaries to UTC for the queries.
        start_dt = tz.localize(datetime.combine(start_date, time.min)).astimezone(
            pytz.UTC
        )
        end_dt = tz.localize(
            datetime.combine(end_date + timedelta(days=1), time.min)
        ).astimezone(pytz.UTC)

        completed_counts = BlockRepository.get_completion_counts(user, start_dt, end_dt)
        open_counts = BlockRepository.get_open_counts(
            user, OPEN_TODO_TYPES, start_dt, end_dt
        )

        counts = {
            "todo": open_counts.get("todo", 0),
            "doing": open_counts.get("doing", 0),
            "later": open_counts.get("later", 0),
            "done": completed_counts.get("done", 0),
            "wontdo": completed_counts.get("wontdo", 0),
        }

        by_day_map = BlockRepository.get_done_counts_by_local_day(
            user, start_dt, end_dt, tz
        )
        by_day: List[Dict[str, Any]] = []
        cursor = start_date
        while cursor <= end_date:
            by_day.append(
                {
                    "date": cursor.isoformat(),
                    "done_count": by_day_map.get(cursor, 0),
                }
            )
            cursor += timedelta(days=1)

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "counts": counts,
            "by_day": by_day,
        }
