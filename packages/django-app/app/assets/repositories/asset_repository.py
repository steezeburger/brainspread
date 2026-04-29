from typing import Optional

from common.repositories.base_repository import BaseRepository

from ..models import Asset


class AssetRepository(BaseRepository):
    model = Asset

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[Asset]:
        queryset = cls.get_queryset()
        if user is not None:
            queryset = queryset.filter(user=user)
        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def find_by_sha256(cls, *, user, sha256: str) -> Optional[Asset]:
        """
        Look up an existing Asset for this user with the given content
        hash. Per-user (not global) so users can't probe other users'
        uploads by guessing hashes.
        """
        if not sha256:
            return None
        return cls.get_queryset().filter(user=user, sha256=sha256).first()
