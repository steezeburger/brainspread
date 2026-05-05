from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Set

import pytz

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_streaks_form import GetStreaksForm
from ..repositories.block_repository import BlockRepository

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
        kind: str = self.form.cleaned_data["kind"]
        as_of: date = self.form.cleaned_data.get("as_of") or user.today()

        lookback_start: date = as_of - timedelta(days=LOOKBACK_DAYS - 1)

        active_days: Set[date]
        if kind == GetStreaksForm.KIND_JOURNAL:
            active_days = set(
                BlockRepository.get_journal_active_dates(user, lookback_start, as_of)
            )
        else:
            tz = user.tz()
            start_dt = tz.localize(
                datetime.combine(lookback_start, time.min)
            ).astimezone(pytz.UTC)
            end_dt = tz.localize(
                datetime.combine(as_of + timedelta(days=1), time.min)
            ).astimezone(pytz.UTC)
            active_days = set(
                BlockRepository.get_completion_active_dates(
                    user, COMPLETED_TYPES, start_dt, end_dt, tz
                )
            )

        # Current streak: count back from as_of while consecutive days are
        # active. If as_of itself isn't active, the current streak is 0 —
        # we don't peek backwards past today's gap.
        current_streak = 0
        cursor: date = as_of
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
