from typing import Iterable, Optional

from django.db.models import QuerySet
from django.utils import timezone

from common.repositories.base_repository import BaseRepository

from ..models import WebArchive


class WebArchiveRepository(BaseRepository):
    model = WebArchive

    @classmethod
    def soft_delete_for_blocks(cls, block_uuids: Iterable[str], user) -> int:
        """Soft-delete every active archive owned by `user` whose block
        is in `block_uuids`, in one query. Used by DeleteBlockCommand to
        clean up a whole deleted subtree's archives at once instead of
        one SELECT + one save() per member (most of whom have no
        archive at all)."""
        return (
            cls.get_queryset()
            .filter(user=user, block__uuid__in=list(block_uuids))
            .update(is_active=False, deleted_at=timezone.now())
        )

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[WebArchive]:
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)
        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_block_uuid(cls, block_uuid: str, user=None) -> Optional[WebArchive]:
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
