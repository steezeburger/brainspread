from datetime import datetime
from typing import Optional
from uuid import UUID

from django.utils import timezone

from common.repositories.base_repository import BaseRepository
from core.models import User

from ..models import OAuthAuthorizationCode, OAuthClient


class OAuthAuthorizationCodeRepository(BaseRepository):
    model = OAuthAuthorizationCode

    @classmethod
    def get_by_hash_for_update(cls, code_hash: str) -> Optional[OAuthAuthorizationCode]:
        """Locks the row so two concurrent exchanges can't both use it.
        Call inside a transaction."""
        try:
            return (
                cls.get_queryset()
                .select_for_update()
                .select_related("client", "user")
                .get(code_hash=code_hash)
            )
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def create(
        cls,
        *,
        code_hash: str,
        client: OAuthClient,
        user: User,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
        resource: str,
        expires_at: datetime,
    ) -> OAuthAuthorizationCode:
        return cls.model.objects.create(
            code_hash=code_hash,
            client=client,
            user=user,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            resource=resource,
            expires_at=expires_at,
        )

    @classmethod
    def mark_used(cls, code: OAuthAuthorizationCode, token_family_id: UUID) -> None:
        code.used_at = timezone.now()
        code.token_family_id = token_family_id
        code.save(update_fields=["used_at", "token_family_id", "modified_at"])
