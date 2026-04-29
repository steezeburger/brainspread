import logging
import os
from typing import TypedDict

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.send_due_reminders_form import SendDueRemindersForm
from knowledge.models import Reminder
from knowledge.services.discord_webhook import post_webhook

logger = logging.getLogger(__name__)


class SendDueRemindersData(TypedDict):
    considered: int
    sent: int
    skipped: int
    failed: int


class SendDueRemindersCommand(AbstractBaseCommand):
    """Dispatch any reminders whose fire_at has arrived.

    Run on a cron-like loop (see the `scheduler` docker service). Uses
    `SELECT FOR UPDATE SKIP LOCKED` so multiple concurrent runners (or a
    stacked run from the previous tick) don't double-send. Skips reminders
    whose block has a `completed_at` set — per issue #59, we don't ping the
    user about work they've already finished.
    """

    def __init__(self, form: SendDueRemindersForm) -> None:
        self.form = form

    def execute(self) -> SendDueRemindersData:
        super().execute()

        now = self.form.cleaned_data.get("now") or timezone.now()
        environment = os.environ.get("ENVIRONMENT", "")

        considered = 0
        sent = 0
        skipped = 0
        failed = 0

        with transaction.atomic():
            # Matches the predicate in issue #59: anything whose fire_at has
            # arrived and hasn't been delivered yet. Previously-failed rows
            # keep `sent_at IS NULL`, so they retry on each tick until they
            # succeed (or the block gets marked completed, which skips them).
            due = (
                Reminder.objects.select_for_update(skip_locked=True)
                .select_related("block", "block__user")
                .filter(
                    fire_at__lte=now,
                    sent_at__isnull=True,
                )
                .exclude(status=Reminder.STATUS_SKIPPED)
            )

            for reminder in due:
                considered += 1
                block = reminder.block

                if block.completed_at is not None:
                    reminder.status = Reminder.STATUS_SKIPPED
                    reminder.sent_at = now
                    reminder.save(update_fields=["status", "sent_at", "modified_at"])
                    skipped += 1
                    continue

                content = _format_content(
                    reminder,
                    block,
                    block.user.discord_user_id,
                    environment,
                )
                url = block.user.discord_webhook_url
                # Look up post_webhook at call time (not via `self.deliver`)
                # so tests can patch the module-level symbol.
                result = post_webhook(url, content)

                if result.ok:
                    reminder.status = Reminder.STATUS_SENT
                    reminder.sent_at = now
                    reminder.last_error = ""
                    reminder.save(
                        update_fields=[
                            "status",
                            "sent_at",
                            "last_error",
                            "modified_at",
                        ]
                    )
                    sent += 1
                else:
                    reminder.status = Reminder.STATUS_FAILED
                    reminder.last_error = result.error
                    reminder.save(update_fields=["status", "last_error", "modified_at"])
                    failed += 1
                    logger.warning(
                        "reminder %s delivery failed: %s",
                        reminder.uuid,
                        result.error,
                    )

        return {
            "considered": considered,
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
        }


_PROD_ENVIRONMENTS = {"prod", "production"}


def _format_content(
    reminder: Reminder,
    block,
    discord_user_id: str = "",
    environment: str = "",
) -> str:
    """Render the Discord message body for a reminder.

    When `discord_user_id` is set, prepends a `<@ID>` mention so the user
    gets a desktop/push notification instead of just a silent channel post.
    When `environment` is set to anything other than prod/production, an
    `[<env>] ` label is prepended so non-prod pings are distinguishable.
    """
    title = (block.content or "").strip().splitlines()[0] if block.content else ""
    if len(title) > 240:
        title = title[:237] + "..."
    due = ""
    if block.scheduled_for:
        due = f" (due {block.scheduled_for.isoformat()})"
    body = f"Reminder: {title}{due}" if title else f"Reminder{due}"
    if discord_user_id:
        body = f"<@{discord_user_id}> {body}"
    env = (environment or "").strip().lower()
    if env and env not in _PROD_ENVIRONMENTS:
        body = f"[{env}] {body}"
    return body
