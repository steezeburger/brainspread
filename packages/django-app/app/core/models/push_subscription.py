from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin
from core.models.user import User


class PushSubscription(UUIDModelMixin, CRUDTimestampsMixin):
    """A browser/device registration for Web Push.

    One user can have many subscriptions — one per browser/device they've
    opted in on. `endpoint` is the push service's URL for this specific
    registration and is globally unique, so re-subscribing from the same
    browser updates the existing row instead of creating a duplicate (see
    PushSubscriptionRepository.upsert).
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "push_subscriptions"
        ordering = ("-created_at",)

    def __str__(self):
        return (
            f"PushSubscription(user={self.user_id}, endpoint={self.endpoint[:40]}...)"
        )
