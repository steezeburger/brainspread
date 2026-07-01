from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.schedule_block_form import ScheduleBlockForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block, Reminder
from ..services.due_dates import build_due_at, combine_local_to_utc
from .touch_page_command import TouchPageCommand


class ScheduleBlockCommand(AbstractBaseCommand):
    """Set or clear a block's due_at, optionally creating reminders at
    user-chosen times. See issue #59 phase 4.

    The due value is all-day by default; a `due_time` flips on a specific
    time of day. Re-scheduling a block always replaces its whole pending
    reminder set rather than accumulating — sent reminders stay as history.
    """

    def __init__(self, form: ScheduleBlockForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        user = self.form.cleaned_data["user"]
        block: Block = self.form.cleaned_data["block"]
        due_date = self.form.cleaned_data.get("due_date")
        due_time = self.form.cleaned_data.get("due_time")
        reminders = self.form.cleaned_data.get("reminders")
        reminder_date = self.form.cleaned_data.get("reminder_date")
        reminder_time = self.form.cleaned_data.get("reminder_time")

        block.due_at, block.due_at_has_time = build_due_at(
            due_date, due_time, user.tz()
        )
        block.save(update_fields=["due_at", "due_at_has_time", "modified_at"])

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        # Replace the block's pending reminder set. Sent reminders are
        # left alone — they're history.
        Reminder.objects.filter(block=block, sent_at__isnull=True).delete()

        # The popover submits `reminders` as a list; the MCP / AI tools
        # still speak the single reminder_date/reminder_time shape, which
        # maps to a one-entry list here.
        if reminders is None and reminder_time:
            reminders = [(reminder_date, reminder_time)]

        # Each reminder can fire on a different day than the due date —
        # the popover's "1 day before" / "1 week before" offsets resolve
        # to concrete dates on the client. An entry without a date
        # defaults to the due date (= classic "remind me day of").
        # Duplicate instants collapse to one so a double-added row
        # doesn't double-ping.
        if reminders:
            tz = block.user.tz()
            seen: set = set()
            for entry_date, entry_time in reminders:
                target_date = entry_date or due_date
                if not target_date:
                    continue
                fire_at = combine_local_to_utc(target_date, entry_time, tz)
                if fire_at in seen:
                    continue
                seen.add(fire_at)
                Reminder.objects.create(
                    block=block,
                    fire_at=fire_at,
                    channel=Reminder.CHANNEL_DISCORD_WEBHOOK,
                )

        return block
