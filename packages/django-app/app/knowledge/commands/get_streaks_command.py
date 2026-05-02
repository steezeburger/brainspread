from datetime import datetime, time, timedelta
from typing import Any, Dict

import pytz
from django.db.models.functions import TruncDate

from common.commands.abstract_base_command import AbstractBaseCommand
from core.helpers import today_for_user

from ..forms.get_streaks_form import GetStreaksForm
from ..models import Block, Page
from ._tool_helpers import user_tz

LOOKBACK_DAYS = 366
COMPLETED_TYPES = ("done", "wontdo")


class GetStreaksCommand(AbstractBaseCommand):
    """Current and longest consecutive-day streak for journaling or
    completion. Days are computed in the user's timezone over a 366-day
    lookback window.
    """

    def __init__(self, form: GetStreaksForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        kind = self.form.cleaned_data["kind"]
        as_of = self.form.cleaned_data.get("as_of") or today_for_user(user)

        lookback_start = as_of - timedelta(days=LOOKBACK_DAYS - 1)

        if kind == GetStreaksForm.KIND_JOURNAL:
            active_days = self._journal_active_days(user, lookback_start, as_of)
        else:
            active_days = self._completion_active_days(user, lookback_start, as_of)

        # Current streak: count back from as_of while consecutive days are
        # active. If as_of itself isn't active, the current streak is 0 —
        # we don't peek backwards past today's gap.
        current_streak = 0
        cursor = as_of
        while cursor in active_days:
            current_streak += 1
            cursor -= timedelta(days=1)

        # Longest streak across the full lookback window.
        longest_streak = 0
        run = 0
        cursor = lookback_start
        while cursor <= as_of:
            if cursor in active_days:
                run += 1
                longest_streak = max(longest_streak, run)
            else:
                run = 0
            cursor += timedelta(days=1)

        last_active = max(active_days) if active_days else None
        return {
            "kind": kind,
            "as_of": as_of.isoformat(),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_active_date": last_active.isoformat() if last_active else None,
        }

    @staticmethod
    def _journal_active_days(user, start_date, end_date) -> set:
        """Days where the user wrote at least one block on the matching
        daily page. An empty auto-created daily shouldn't count.
        """
        page_ids = Page.objects.filter(
            user=user,
            page_type="daily",
            date__gte=start_date,
            date__lte=end_date,
        ).values_list("id", flat=True)
        day_rows = (
            Block.objects.filter(page_id__in=list(page_ids))
            .values_list("page__date", flat=True)
            .distinct()
        )
        return {d for d in day_rows if d is not None}

    @staticmethod
    def _completion_active_days(user, start_date, end_date) -> set:
        """Days where the user completed at least one block in their tz."""
        tz = user_tz(user)
        start_dt = tz.localize(datetime.combine(start_date, time.min)).astimezone(
            pytz.UTC
        )
        end_dt = tz.localize(
            datetime.combine(end_date + timedelta(days=1), time.min)
        ).astimezone(pytz.UTC)
        rows = (
            Block.objects.filter(
                user=user,
                block_type__in=COMPLETED_TYPES,
                completed_at__gte=start_dt,
                completed_at__lt=end_dt,
            )
            .annotate(local_day=TruncDate("completed_at", tzinfo=tz))
            .values_list("local_day", flat=True)
            .distinct()
        )
        return {d for d in rows if d is not None}
