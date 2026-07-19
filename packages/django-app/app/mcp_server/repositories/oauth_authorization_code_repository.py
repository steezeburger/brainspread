import secrets
from typing import Optional

from django.utils import timezone

from common.repositories.base_repository import BaseRepository
from core.models import User
from mcp_server.constants import AUTHORIZATION_CODE_LIFETIME
from mcp_server.models import OAuthAuthorizationCode, OAuthClient


class OAuthAuthorizationCodeRepository(BaseRepository):
    model = OAuthAuthorizationCode

    @classmethod
    def create(
        cls,
        *,
        client: OAuthClient,
        user: User,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> OAuthAuthorizationCode:
        return cls.model.objects.create(
            code=secrets.token_urlsafe(32),
            client=client,
            user=user,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=timezone.now() + AUTHORIZATION_CODE_LIFETIME,
        )

    @classmethod
    def get_by_code(cls, code: str) -> Optional[OAuthAuthorizationCode]:
        try:
            return cls.get_queryset().select_related("client", "user").get(code=code)
        except OAuthAuthorizationCode.DoesNotExist:
            return None

    @classmethod
    def mark_used(cls, auth_code: OAuthAuthorizationCode) -> OAuthAuthorizationCode:
        auth_code.used_at = timezone.now()
        auth_code.save(update_fields=["used_at", "modified_at"])
        return auth_code
