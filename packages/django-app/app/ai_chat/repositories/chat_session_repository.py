from typing import List, Optional

from django.db.models import Count, Q, QuerySet

from common.repositories.base_repository import BaseRepository
from core.models import User

from ..models import ChatSession


class ChatSessionRepository(BaseRepository):
    model = ChatSession

    @classmethod
    def create_session(cls, user: User) -> ChatSession:
        return cls.model.objects.create(user=user)

    @classmethod
    def get_history_for_user(
        cls, user: User, limit: int, exclude_session_id: Optional[str] = None
    ) -> List[ChatSession]:
        """Past sessions for the user, newest first, annotated with
        message_count. `exclude_session_id` drops the active session
        when the executor knows it.
        """
        qs = (
            cls.get_queryset()
            .filter(user=user)
            .annotate(message_count=Count("messages"))
            .order_by("-created_at")
        )
        if exclude_session_id:
            qs = qs.exclude(uuid=exclude_session_id)
        return list(qs[:limit])

    @classmethod
    def get_for_user(cls, uuid: str, user: User) -> Optional[ChatSession]:
        try:
            return cls.get_queryset().get(uuid=uuid, user=user)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def list_for_user(cls, user: User, search: str = "") -> QuerySet:
        """Sessions for the user, newest-modified first. When `search`
        is non-empty, narrow to titles or message contents that match
        it case-insensitively. distinct() because the join through
        messages can multiply rows when many messages match in one
        session.
        """
        qs = cls.get_queryset().filter(user=user)
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(messages__content__icontains=search)
            ).distinct()
        return qs.order_by("-modified_at")
