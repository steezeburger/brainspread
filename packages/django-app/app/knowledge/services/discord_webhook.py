from typing import List, NamedTuple, Optional

import httpx


class DiscordDeliveryResult(NamedTuple):
    ok: bool
    error: str


def post_webhook(
    url: str,
    content: str = "",
    *,
    embeds: Optional[List[dict]] = None,
    timeout: float = 10.0,
) -> DiscordDeliveryResult:
    """POST a message to a Discord webhook URL.

    `content` is the plain-text body of the message — keep this for the
    `<@ID>` mention since mentions inside `embeds` don't trigger
    notifications. `embeds` is a list of Discord embed objects (max 10)
    and is where the rendered reminder lives. At least one of the two
    must be non-empty.

    Returns `DiscordDeliveryResult(ok, error)`. On any non-2xx response or
    connection error, `ok=False` and `error` describes the failure — the
    caller is responsible for recording that on the reminder row.
    """
    if not url:
        return DiscordDeliveryResult(False, "no webhook url configured")

    if not content and not embeds:
        return DiscordDeliveryResult(False, "no content or embeds to send")

    # `allowed_mentions.parse=["users"]` lets the `<@ID>` mention in
    # `content` actually ping the user — Discord drops mentions from
    # webhook payloads otherwise.
    payload: dict = {"allowed_mentions": {"parse": ["users"]}}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds

    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as e:
        return DiscordDeliveryResult(False, f"request failed: {e}")

    if 200 <= response.status_code < 300:
        return DiscordDeliveryResult(True, "")
    return DiscordDeliveryResult(
        False,
        f"discord returned {response.status_code}: {response.text[:200]}",
    )
