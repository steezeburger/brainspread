from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Q, QuerySet
from django.utils import timezone

from common.repositories.base_repository import BaseRepository
from core.helpers import hash_mcp_access_key
from core.models import McpAccessToken, User

# last_used_at is informational, so don't write it on every MCP call.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class McpAccessTokenRepository(BaseRepository):
    model = McpAccessToken

    @classmethod
    def list_unrevoked_for_user(cls, user: User) -> QuerySet:
        return (
            cls.get_queryset()
            .filter(user=user, revoked_at__isnull=True)
            .order_by("-created_at")
        )

    @classmethod
    def get_unrevoked_by_uuid(cls, uuid: str, user: User) -> Optional[McpAccessToken]:
        try:
            return cls.get_queryset().get(uuid=uuid, user=user, revoked_at__isnull=True)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_usable_by_key(cls, key: str) -> Optional[McpAccessToken]:
        """The unrevoked, unexpired token for ``key`` whose user is active."""
        now = timezone.now()
        try:
            return (
                cls.get_queryset()
                .select_related("user")
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .get(
                    key_hash=hash_mcp_access_key(key),
                    revoked_at__isnull=True,
                    user__is_active=True,
                )
            )
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def create(
        cls,
        *,
        user: User,
        name: str,
        key_prefix: str,
        key_hash: str,
        expires_at: Optional[datetime],
    ) -> McpAccessToken:
        return cls.model.objects.create(
            user=user,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            expires_at=expires_at,
        )

    @classmethod
    def mark_used(cls, token: McpAccessToken) -> None:
        now = timezone.now()
        if token.last_used_at and now - token.last_used_at < LAST_USED_RESOLUTION:
            return
        # .update() so modified_at keeps meaning "edited", not "used".
        cls.get_queryset().filter(pk=token.pk).update(last_used_at=now)
        token.last_used_at = now

    @classmethod
    def revoke(cls, token: McpAccessToken) -> McpAccessToken:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "modified_at"])
        return token
