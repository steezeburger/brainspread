from datetime import datetime

import pytz

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.schedule_block_form import ScheduleBlockForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block, Reminder
from .touch_page_command import TouchPageCommand


class ScheduleBlockCommand(AbstractBaseCommand):
    """Set or clear a block's scheduled_for, optionally creating a reminder
    at a user-chosen time on that date. See issue #59 phase 4.

    Re-scheduling a block always replaces its pending reminder rather than
    accumulating new ones — sent reminders stay as history.
    """

    def __init__(self, form: ScheduleBlockForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        user = self.form.cleaned_data["user"]
        block: Block = self.form.cleaned_data["block"]
        scheduled_for = self.form.cleaned_data.get("scheduled_for")
        reminder_date = self.form.cleaned_data.get("reminder_date")
        reminder_time = self.form.cleaned_data.get("reminder_time")

        block.scheduled_for = scheduled_for
        block.save(update_fields=["scheduled_for", "modified_at"])

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        # Replace any pending reminder for this block. Sent reminders are
        # left alone — they're history.
        Reminder.objects.filter(block=block, sent_at__isnull=True).delete()

        # The reminder can fire on a different day than the due date — the
        # popover's "1 day before" / "1 week before" offsets resolve to a
        # concrete date on the client and submit it as `reminder_date`. If
        # absent, default to the due date (= classic "remind me day of").
        if reminder_time:
            target_date = reminder_date or scheduled_for
            if target_date:
                fire_at = _to_utc(target_date, reminder_time, block.user.timezone)
                Reminder.objects.create(
                    block=block,
                    fire_at=fire_at,
                    channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
                )

        return block


def _to_utc(scheduled_for, reminder_time, tz_name: str) -> "datetime":
    """Combine date + time in the user's tz, return as UTC."""
    try:
        tz = pytz.timezone(tz_name or "UTC")
    except pytz.UnknownTimeZoneError:
        tz = pytz.UTC
    naive = datetime.combine(scheduled_for, reminder_time)
    return tz.localize(naive).astimezone(pytz.UTC)
