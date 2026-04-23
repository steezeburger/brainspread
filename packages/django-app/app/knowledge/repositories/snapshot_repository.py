from typing import Optional

from django.db.models import QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import Snapshot


class SnapshotRepository(BaseRepository):
    model = Snapshot

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[Snapshot]:
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)
        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_block_uuid(cls, block_uuid: str, user=None) -> Optional[Snapshot]:
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)
        try:
            return queryset.get(block__uuid=block_uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_for_user(cls, user) -> QuerySet:
        return cls.get_queryset().filter(user=user)
