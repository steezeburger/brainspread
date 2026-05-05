from typing import Any, Dict

import pytz
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import GetCurrentTimeForm


class GetCurrentTimeCommand(AbstractBaseCommand):
    """Return the current date/time in the user's timezone.

    Backs the assistant's get_current_time tool — the model needs a
    user-local 'now' before scheduling reminders against time-relative
    phrases like 'in 5 minutes'.
    """

    def __init__(self, form: GetCurrentTimeForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        tz_name = user.timezone or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.UTC
            tz_name = "UTC"
        now_local = timezone.now().astimezone(tz)
        return {
            "now": now_local.isoformat(),
            "date": now_local.date().isoformat(),
            "time": now_local.strftime("%H:%M"),
            "weekday": now_local.strftime("%A"),
            "timezone": tz_name,
        }
