import logging
import os
from typing import Dict, List, Tuple, TypedDict

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.send_due_reminders_form import SendDueRemindersForm
from knowledge.models import Reminder, ReminderAction
from knowledge.services.discord_webhook import post_webhook
from knowledge.services.reminder_actions import (
    build_action_url,
    create_action_tokens,
)

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
        # Per-PR staging deploys plumb these through the workflow so
        # reminders carry a clickable "PR #N" in the embed author —
        # handy when multiple per-PR staging envs all ping the same
        # Discord channel and you need to know which PR each ping
        # came from. Both empty in production / local.
        pr_number = os.environ.get("STAGING_PR_NUMBER", "")
        pr_url = os.environ.get("STAGING_PR_URL", "")

        considered = 0
        sent = 0
        skipped = 0
        failed = 0

        with transaction.atomic():
            # Matches the predicate in issue #59: anything whose fire_at has
            # arrived and hasn't been delivered yet. Previously-failed rows
            # keep `sent_at IS NULL`, so they retry on each tick until they
            # succeed (or the block gets marked completed, which skips them).
            # Pull `block__page` along too — the embed footer reads
            # `block.page.title` and we don't want to N+1 across the loop.
            due = (
                Reminder.objects.select_for_update(skip_locked=True)
                .select_related("block", "block__user", "block__page")
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

                # Mint the per-action tokens before posting so the
                # links in the message resolve. Failing to mint tokens
                # shouldn't block the reminder itself — fall back to a
                # link-less embed so the user still gets pinged.
                action_urls = _action_urls_for(reminder, settings.SITE_URL, now)

                content, embeds = _build_payload(
                    reminder,
                    block,
                    discord_user_id=block.user.discord_user_id,
                    environment=environment,
                    site_url=settings.SITE_URL,
                    pr_number=pr_number,
                    pr_url=pr_url,
                    action_urls=action_urls,
                )
                url = block.user.discord_webhook_url
                # Look up post_webhook at call time (not via `self.deliver`)
                # so tests can patch the module-level symbol.
                result = post_webhook(url, content, embeds=embeds)

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

# Color stripe on the embed's left edge — a quick visual cue for which
# deploy a ping came from. Decimal RGB ints (Discord doesn't accept hex
# strings).
_COLOR_PROD = 0x6366F1  # indigo
_COLOR_STAGING = 0xF59E0B  # amber
_COLOR_DEFAULT = 0x6B7280  # gray (local / unknown)


def _action_urls_for(reminder: Reminder, site_url: str, now) -> Dict[str, str]:
    """Mint reminder-action tokens and return their absolute URLs.

    Returns `{action: url}`. Skips when SITE_URL isn't a real http(s)
    URL — without a working absolute base, the embed links would 404 so
    the reminder is better off without them. Errors are swallowed so a
    DB hiccup creating tokens doesn't block delivery; we log + carry
    on. Worst case the user gets a notification with no quick-actions.
    """
    if not site_url or not site_url.startswith(("http://", "https://")):
        return {}
    try:
        rows = create_action_tokens(reminder, now=now)
    except Exception as e:
        logger.warning(
            "failed to mint reminder action tokens for %s: %s",
            reminder.uuid,
            e,
        )
        return {}
    return {
        action: build_action_url(site_url, row.token) for action, row in rows.items()
    }


def _build_payload(
    reminder: Reminder,
    block,
    *,
    discord_user_id: str = "",
    environment: str = "",
    site_url: str = "",
    pr_number: str = "",
    pr_url: str = "",
    action_urls: Dict[str, str] | None = None,
) -> Tuple[str, List[dict]]:
    """Return `(content, [embed])` for the Discord webhook payload.

    `content` carries only the `<@ID>` mention so Discord delivers the
    push/desktop notification (mentions inside embeds don't trigger
    notifications). The embed holds the actual reminder layout — same
    skeleton regardless of title length, due date, or env/PR context,
    so messages line up consistently in the channel:

        [author: "<env> · PR #<n>"]   ← clickable to PR (when set)
        <block content first line>    ← bold title, NOT a link
        [Open block →](<page-url>)    ← description, the actionable link
        [Due: YYYY-MM-DD]             ← inline field (only when scheduled)
        on <page title>               ← footer, page context
        <relative time>               ← timestamp, rendered by Discord
    """
    title = (block.content or "").strip().splitlines()[0] if block.content else ""
    if len(title) > 240:
        title = title[:237] + "..."
    if not title:
        # Embeds can't have an empty title; fall back to a stable label
        # so the embed renders cleanly for blocks that are images or
        # otherwise content-less.
        title = "Reminder"

    embed: dict = {
        "title": title,
        "color": _color_for_env(environment),
    }

    # Discord renders this as a localized relative time (e.g. "today at
    # 3:14 PM") at the bottom-right of the embed.
    if reminder.fire_at:
        embed["timestamp"] = reminder.fire_at.isoformat()

    description_lines: List[str] = []
    page_link = _page_link(block, site_url)
    if page_link:
        description_lines.append(f"[Open block →]({page_link})")

    action_line = _action_links_line(action_urls or {})
    if action_line:
        description_lines.append(action_line)

    if description_lines:
        # Two newlines so Discord renders each link group on its own
        # line without collapsing the second into a continuation.
        embed["description"] = "\n\n".join(description_lines)

    if block.scheduled_for:
        embed["fields"] = [
            {
                "name": "Due",
                "value": block.scheduled_for.isoformat(),
                "inline": True,
            }
        ]

    author = _author_block(environment, pr_number, pr_url)
    if author:
        embed["author"] = author

    if block.page_id and block.page.title:
        embed["footer"] = {"text": f"on {block.page.title}"}

    content = f"<@{discord_user_id}>" if discord_user_id else ""
    return content, [embed]


def _color_for_env(environment: str) -> int:
    env = (environment or "").strip().lower()
    if env in _PROD_ENVIRONMENTS:
        return _COLOR_PROD
    if env == "staging":
        return _COLOR_STAGING
    return _COLOR_DEFAULT


def _author_block(environment: str, pr_number: str, pr_url: str) -> dict:
    """Build the embed `author` dict with env tag + PR token.

    Empty in production (the env label "prod" adds no signal) and when
    there's neither env nor PR info to surface. The PR URL only attaches
    when it's a real http(s) URL, otherwise the author renders as plain
    non-clickable text.
    """
    env = (environment or "").strip()
    show_env = bool(env) and env.lower() not in _PROD_ENVIRONMENTS
    env_label = env if show_env else ""
    pr_label = f"PR #{pr_number}" if pr_number else ""
    bits = [b for b in (env_label, pr_label) if b]
    if not bits:
        return {}
    author: dict = {"name": " · ".join(bits)}
    if pr_url and pr_url.startswith(("http://", "https://")):
        author["url"] = pr_url
    return author


_ACTION_LABELS = [
    (ReminderAction.ACTION_COMPLETE, "Mark done"),
    (ReminderAction.ACTION_SNOOZE_1H, "Snooze 1h"),
    (ReminderAction.ACTION_SNOOZE_1D, "Snooze 1d"),
]


def _action_links_line(action_urls: Dict[str, str]) -> str:
    """Render the inline action-link row, e.g.
    `[Mark done](u1) · [Snooze 1h](u2) · [Snooze 1d](u3)`.

    Returns "" when no urls are supplied — the embed is then rendered
    without a quick-action row, same as before this feature.
    """
    parts: List[str] = []
    for action, label in _ACTION_LABELS:
        url = action_urls.get(action)
        if url:
            parts.append(f"[{label}]({url})")
    return " · ".join(parts)


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
