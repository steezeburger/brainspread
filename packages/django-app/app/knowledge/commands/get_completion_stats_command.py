from datetime import datetime, time, timedelta
from typing import Any, Dict, List

import pytz
from django.db.models import Count
from django.db.models.functions import TruncDate

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_completion_stats_form import GetCompletionStatsForm
from ..models import Block
from ._tool_helpers import user_tz

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

        tz = user_tz(user)
        # Convert the user-local day boundaries to UTC for the queries.
        start_dt = tz.localize(datetime.combine(start_date, time.min)).astimezone(
            pytz.UTC
        )
        end_dt = tz.localize(
            datetime.combine(end_date + timedelta(days=1), time.min)
        ).astimezone(pytz.UTC)

        completed_qs = Block.objects.filter(
            user=user,
            completed_at__gte=start_dt,
            completed_at__lt=end_dt,
        )
        completed_counts = dict(
            completed_qs.values_list("block_type").annotate(c=Count("id"))
        )

        open_qs = Block.objects.filter(
            user=user,
            block_type__in=OPEN_TODO_TYPES,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        open_counts = dict(open_qs.values_list("block_type").annotate(c=Count("id")))

        counts = {
            "todo": int(open_counts.get("todo", 0)),
            "doing": int(open_counts.get("doing", 0)),
            "later": int(open_counts.get("later", 0)),
            "done": int(completed_counts.get("done", 0)),
            "wontdo": int(completed_counts.get("wontdo", 0)),
        }

        done_only = (
            completed_qs.filter(block_type="done")
            .annotate(local_day=TruncDate("completed_at", tzinfo=tz))
            .values("local_day")
            .annotate(c=Count("id"))
            .order_by("local_day")
        )
        by_day_map = {row["local_day"]: int(row["c"]) for row in done_only}
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
