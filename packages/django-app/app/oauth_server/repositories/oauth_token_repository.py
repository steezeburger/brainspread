import uuid
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Min, QuerySet
from django.utils import timezone

from common.repositories.base_repository import BaseRepository
from core.models import User

from ..models import OAuthClient, OAuthToken

# last_used_at is informational, so don't write it on every MCP call.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class OAuthTokenRepository(BaseRepository):
    model = OAuthToken

    @classmethod
    def get_usable_by_access_hash(cls, access_hash: str) -> Optional[OAuthToken]:
        now = timezone.now()
        try:
            return (
                cls.get_queryset()
                .select_related("user")
                .get(
                    access_token_hash=access_hash,
                    access_expires_at__gt=now,
                    replaced_at__isnull=True,
                    revoked_at__isnull=True,
                    user__is_active=True,
                )
            )
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_refresh_hash_for_update(cls, refresh_hash: str) -> Optional[OAuthToken]:
        """Locks the row so concurrent refreshes serialize. Call inside a
        transaction."""
        try:
            return (
                cls.get_queryset()
                .select_for_update()
                .select_related("client", "user")
                .get(refresh_token_hash=refresh_hash)
            )
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def create(
        cls,
        *,
        user: User,
        client: OAuthClient,
        family_id: Optional[uuid.UUID],
        access_token_hash: str,
        access_expires_at: datetime,
        refresh_token_hash: str,
        refresh_expires_at: datetime,
        scope: str,
        resource: str,
    ) -> OAuthToken:
        return cls.model.objects.create(
            user=user,
            client=client,
            # A new family is a new connection; rotation passes the old one.
            family_id=family_id or uuid.uuid4(),
            access_token_hash=access_token_hash,
            access_expires_at=access_expires_at,
            refresh_token_hash=refresh_token_hash,
            refresh_expires_at=refresh_expires_at,
            scope=scope,
            resource=resource,
        )

    @classmethod
    def mark_replaced(cls, token: OAuthToken) -> None:
        token.replaced_at = timezone.now()
        token.save(update_fields=["replaced_at", "modified_at"])

    @classmethod
    def revoke_family(cls, family_id: uuid.UUID, user: Optional[User] = None) -> int:
        qs = cls.get_queryset().filter(family_id=family_id, revoked_at__isnull=True)
        if user is not None:
            qs = qs.filter(user=user)
        return qs.update(revoked_at=timezone.now())

    @classmethod
    def family_exists_for_user(cls, family_id: uuid.UUID, user: User) -> bool:
        return (
            cls.get_queryset()
            .filter(family_id=family_id, user=user, revoked_at__isnull=True)
            .exists()
        )

    @classmethod
    def list_active_for_user(cls, user: User) -> QuerySet:
        """The current (unrotated, unrevoked, refreshable) token of each
        connection — at most one per family."""
        return (
            cls.get_queryset()
            .select_related("client")
            .filter(
                user=user,
                replaced_at__isnull=True,
                revoked_at__isnull=True,
                refresh_expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
        )

    @classmethod
    def family_started_at(
        cls, family_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, datetime]:
        rows = (
            cls.get_queryset()
            .filter(family_id__in=family_ids)
            .values("family_id")
            .annotate(started=Min("created_at"))
        )
        return {row["family_id"]: row["started"] for row in rows}

    @classmethod
    def mark_used(cls, token: OAuthToken) -> None:
        now = timezone.now()
        if token.last_used_at and now - token.last_used_at < LAST_USED_RESOLUTION:
            return
        # .update() so modified_at keeps meaning "edited", not "used".
        cls.get_queryset().filter(pk=token.pk).update(last_used_at=now)
        token.last_used_at = now
