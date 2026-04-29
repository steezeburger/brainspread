from typing import NamedTuple

import httpx


class DiscordDeliveryResult(NamedTuple):
    ok: bool
    error: str


def post_webhook(
    url: str, content: str, *, timeout: float = 10.0
) -> DiscordDeliveryResult:
    """POST a message to a Discord webhook URL.

    Returns `DiscordDeliveryResult(ok, error)`. On any non-2xx response or
    connection error, `ok=False` and `error` describes the failure — the
    caller is responsible for recording that on the reminder row.
    """
    if not url:
        return DiscordDeliveryResult(False, "no webhook url configured")

    try:
        response = httpx.post(url, json={"content": content}, timeout=timeout)
    except httpx.HTTPError as e:
        return DiscordDeliveryResult(False, f"request failed: {e}")

    if 200 <= response.status_code < 300:
        return DiscordDeliveryResult(True, "")
    return DiscordDeliveryResult(
        False,
        f"discord returned {response.status_code}: {response.text[:200]}",
    )
