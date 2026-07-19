import secrets
from typing import Optional

from django.utils import timezone

from common.repositories.base_repository import BaseRepository
from core.models import User
from mcp_server.constants import ACCESS_TOKEN_LIFETIME
from mcp_server.models import OAuthAccessToken, OAuthClient


class OAuthAccessTokenRepository(BaseRepository):
    model = OAuthAccessToken

    @classmethod
    def create_for_user(cls, *, client: OAuthClient, user: User) -> OAuthAccessToken:
        return cls.model.objects.create(
            access_token=secrets.token_urlsafe(32),
            refresh_token=secrets.token_urlsafe(32),
            client=client,
            user=user,
            access_expires_at=timezone.now() + ACCESS_TOKEN_LIFETIME,
        )

    @classmethod
    def get_active_by_access_token(
        cls, access_token: str
    ) -> Optional[OAuthAccessToken]:
        """Token usable as a bearer credential: not revoked, not expired."""
        try:
            return (
                cls.get_queryset()
                .select_related("user")
                .get(
                    access_token=access_token,
                    revoked_at__isnull=True,
                    access_expires_at__gt=timezone.now(),
                )
            )
        except OAuthAccessToken.DoesNotExist:
            return None

    @classmethod
    def get_active_by_refresh_token(
        cls, refresh_token: str
    ) -> Optional[OAuthAccessToken]:
        """Refresh tokens outlive the access token; only revocation kills them."""
        try:
            return (
                cls.get_queryset()
                .select_related("client", "user")
                .get(refresh_token=refresh_token, revoked_at__isnull=True)
            )
        except OAuthAccessToken.DoesNotExist:
            return None

    @classmethod
    def revoke(cls, token: OAuthAccessToken) -> OAuthAccessToken:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "modified_at"])
        return token
