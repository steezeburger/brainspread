from typing import List

from common.repositories.base_repository import BaseRepository
from core.models.push_subscription import PushSubscription
from core.models.user import User


class PushSubscriptionRepository(BaseRepository):
    model = PushSubscription

    @classmethod
    def get_for_user(cls, user: User) -> List[PushSubscription]:
        return list(cls.get_queryset().filter(user=user))

    @classmethod
    def upsert(
        cls, *, user: User, endpoint: str, p256dh: str, auth: str, user_agent: str = ""
    ) -> PushSubscription:
        """Register (or re-register) a browser's push subscription.

        `endpoint` is the natural key — a browser re-subscribing (e.g.
        after the old registration expired) reuses the same row rather
        than piling up a dead duplicate, even if the keys rotated.
        """
        subscription, _ = cls.model.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": user,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": user_agent,
            },
        )
        return subscription

    @classmethod
    def delete_for_user_by_endpoint(cls, user: User, endpoint: str) -> int:
        deleted, _ = cls.get_queryset().filter(user=user, endpoint=endpoint).delete()
        return deleted

    @classmethod
    def delete_by_endpoint(cls, endpoint: str) -> int:
        """Remove a subscription by endpoint regardless of owner.

        Used when a push send comes back 404/410 — the push service is
        telling us the endpoint is gone, so it should be forgotten no
        matter which user row references it.
        """
        deleted, _ = cls.model.objects.filter(endpoint=endpoint).delete()
        return deleted
