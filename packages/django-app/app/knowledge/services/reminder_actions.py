from datetime import timedelta
from typing import Dict, List, Optional

from django.utils import timezone

from knowledge.models import Reminder, ReminderAction


def create_action_tokens(
    reminder: Reminder,
    *,
    actions: Optional[List[str]] = None,
    ttl: Optional[timedelta] = None,
    now: Optional["timezone.datetime"] = None,
) -> Dict[str, ReminderAction]:
    """Mint one ReminderAction per action for `reminder`.

    Returns a `{action: ReminderAction}` dict so callers can look up
    the per-action token without re-querying. `actions` defaults to
    the full set we surface in Discord (`complete`, `snooze_1h`,
    `snooze_1d`) — pass a subset if you ever want to hide an action.
    """
    moment = now or timezone.now()
    expires_at = moment + (ttl or ReminderAction.DEFAULT_TTL)
    chosen = actions or [
        ReminderAction.ACTION_COMPLETE,
        ReminderAction.ACTION_SNOOZE_1H,
        ReminderAction.ACTION_SNOOZE_1D,
    ]

    out: Dict[str, ReminderAction] = {}
    for action in chosen:
        out[action] = ReminderAction.objects.create(
            reminder=reminder,
            action=action,
            expires_at=expires_at,
        )
    return out


def build_action_url(site_url: str, token: str) -> str:
    """Absolute URL to the public action endpoint for `token`.

    Returns "" when SITE_URL isn't a real http(s) URL, matching the
    existing `_page_link` skip — the embed should render without
    action links rather than with broken ones.
    """
    if not site_url or not site_url.startswith(("http://", "https://")):
        return ""
    base = site_url.rstrip("/")
    return f"{base}/knowledge/r/{token}/"
