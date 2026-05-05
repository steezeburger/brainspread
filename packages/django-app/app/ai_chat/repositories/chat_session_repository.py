from typing import List, Optional

from django.db.models import Count

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
