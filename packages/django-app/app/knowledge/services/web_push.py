import json
from typing import NamedTuple

from django.conf import settings
from pywebpush import WebPushException, webpush


class WebPushDeliveryResult(NamedTuple):
    ok: bool
    error: str
    # True when the push service told us the subscription is gone
    # (404/410) — the caller should delete it rather than keep retrying.
    dead: bool = False


def post_web_push(
    subscription, payload: dict, *, timeout: float = 10.0
) -> WebPushDeliveryResult:
    """Send one Web Push message to one subscription.

    `subscription` is a core.models.PushSubscription instance (or
    anything exposing the same `.endpoint` / `.p256dh` / `.auth`
    attributes).
    """
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return WebPushDeliveryResult(False, "VAPID keys not configured")

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            timeout=timeout,
        )
        return WebPushDeliveryResult(True, "")
    except WebPushException as e:
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None)
        dead = status_code in (404, 410)
        return WebPushDeliveryResult(False, str(e), dead=dead)
