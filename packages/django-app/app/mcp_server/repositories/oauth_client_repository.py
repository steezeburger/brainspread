import secrets
from typing import List, Optional

from common.repositories.base_repository import BaseRepository
from mcp_server.models import OAuthClient


class OAuthClientRepository(BaseRepository):
    model = OAuthClient

    @classmethod
    def create(cls, *, client_name: str, redirect_uris: List[str]) -> OAuthClient:
        return cls.model.objects.create(
            client_id=secrets.token_urlsafe(24),
            client_name=client_name,
            redirect_uris=redirect_uris,
        )

    @classmethod
    def get_by_client_id(cls, client_id: str) -> Optional[OAuthClient]:
        try:
            return cls.get_queryset().get(client_id=client_id)
        except OAuthClient.DoesNotExist:
            return None
