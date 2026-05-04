import logging
import os
from typing import TypedDict

from django.conf import settings
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
                    settings.SITE_URL,
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
    site_url: str = "",
) -> str:
    """Render the Discord message body for a reminder.

    Layout:

        [<env>] <@ID> Reminder: due <YYYY-MM-DD> — [<title>](<url>)

    The leading bits are conditional: `<@ID>` only when a discord user id
    is set, the env label only outside prod/production, the "due …" only
    when the block is scheduled, and the title-as-markdown-link only
    when SITE_URL is real http(s) (we still need a clickable target to
    bother with the markdown wrapper). The due date sits before the
    title so reminders all start with the same fixed-width prefix
    regardless of title length, and the title itself is the link text
    so the URL doesn't get tacked onto a separate line.
    """
    title = (block.content or "").strip().splitlines()[0] if block.content else ""
    if len(title) > 240:
        title = title[:237] + "..."

    page_link = _page_link(block, site_url)

    # Title-as-link when we have both; otherwise fall back through the
    # cases. `<url>` (angle-bracket form) suppresses Discord's auto
    # preview embed when we have no title to wrap around the URL.
    if title and page_link:
        body_tail = f"[{_escape_link_text(title)}]({page_link})"
    elif title:
        body_tail = title
    elif page_link:
        body_tail = f"<{page_link}>"
    else:
        body_tail = ""

    if block.scheduled_for:
        prefix = f"Reminder: due {block.scheduled_for.isoformat()}"
        body = f"{prefix} — {body_tail}" if body_tail else prefix
    else:
        body = f"Reminder: {body_tail}" if body_tail else "Reminder"

    if discord_user_id:
        body = f"<@{discord_user_id}> {body}"
    env = (environment or "").strip().lower()
    if env and env not in _PROD_ENVIRONMENTS:
        body = f"[{env}] {body}"
    return body


def _escape_link_text(text: str) -> str:
    """Escape characters that would break Markdown link text.

    Discord's parser uses `]` to terminate the link text and `\\` as
    the escape char, so back-slash both. Other markdown chars
    (asterisks, underscores, etc.) we leave alone — the title was
    authored as plain block content and rendering its incidental
    inline formatting is fine.
    """
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _page_link(block, site_url: str) -> str:
    """Build an absolute URL to the page that contains the block.

    Includes a `#block-<uuid>` fragment so the editor can scroll
    straight to the originating block on load — see
    `scrollToHashBlock` in Page.js. Skips when SITE_URL isn't a
    real http(s) URL (the default placeholder is just "0.0.0.0",
    which would produce broken links).
    """
    if not site_url or not site_url.startswith(("http://", "https://")):
        return ""
    if not block.page_id or not block.page.slug:
        return ""
    base = site_url.rstrip("/")
    return f"{base}/knowledge/page/{block.page.slug}/#block-{block.uuid}"
