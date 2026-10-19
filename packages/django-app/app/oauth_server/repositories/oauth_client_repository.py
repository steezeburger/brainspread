from typing import Optional

from common.repositories.base_repository import BaseRepository

from ..models import OAuthClient


class OAuthClientRepository(BaseRepository):
    model = OAuthClient

    @classmethod
    def get_by_client_id(cls, client_id: str) -> Optional[OAuthClient]:
        try:
            return cls.get_queryset().get(client_id=client_id)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def create(
        cls, *, client_id: str, client_name: str, redirect_uris: list[str]
    ) -> OAuthClient:
        return cls.model.objects.create(
            client_id=client_id, client_name=client_name, redirect_uris=redirect_uris
        )
