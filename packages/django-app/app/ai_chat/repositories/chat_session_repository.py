from typing import List, Optional

from django.db.models import Count, Max, Q, QuerySet

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
    def list_for_user(
        cls, user: User, search: str = "", favorites_only: bool = False
    ) -> QuerySet:
        """Sessions for the user, favorited first then newest-modified.
        When `search` is non-empty, narrow to titles or message contents
        that match it case-insensitively. When `favorites_only` is True,
        only return favorited sessions. distinct() because the join
        through messages can multiply rows when many messages match in
        one session.
        """
        qs = cls.get_queryset().filter(user=user)
        if favorites_only:
            qs = qs.filter(is_favorited=True)
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(messages__content__icontains=search)
            ).distinct()
        # Favorites pin to the top so the "Pinned" section in the UI
        # can be built off the same query without a second round-trip.
        # Within favorites: user-curated favorite_position wins, then
        # -modified_at as a tiebreaker. Non-favorites fall through to
        # -modified_at (favorite_position is 0 for all non-favorites,
        # so it's a no-op on that side).
        return qs.order_by("-is_favorited", "favorite_position", "-modified_at")

    @classmethod
    def set_favorited(
        cls, uuid: str, user: User, is_favorited: bool
    ) -> Optional[ChatSession]:
        session = cls.get_for_user(uuid=uuid, user=user)
        if session is None:
            return None
        update_fields = ["is_favorited", "modified_at"]
        session.is_favorited = is_favorited
        if is_favorited:
            # Append to the end of the Pinned section. Without this,
            # newly-favorited chats would all share favorite_position=0
            # and tiebreak only on -modified_at, which would shuffle
            # the older pinned items every time a new one was added.
            session.favorite_position = cls.next_favorite_position(user)
            update_fields.append("favorite_position")
        session.save(update_fields=update_fields)
        return session

    @classmethod
    def list_favorited(cls, user: User) -> List[ChatSession]:
        """Favorited sessions in their curated order, for the reorder
        command and the post-reorder response."""
        return list(
            cls.get_queryset()
            .filter(user=user, is_favorited=True)
            .order_by("favorite_position", "-modified_at")
        )

    @classmethod
    def next_favorite_position(cls, user: User) -> int:
        """Next-highest favorite_position so a newly-pinned chat lands
        at the end of the Pinned section rather than racing with the
        existing 0-positioned rows."""
        current_max = (
            cls.get_queryset()
            .filter(user=user, is_favorited=True)
            .aggregate(max_pos=Max("favorite_position"))["max_pos"]
        )
        return 0 if current_max is None else current_max + 1

    @classmethod
    def update_title(cls, uuid: str, user: User, title: str) -> Optional[ChatSession]:
        session = cls.get_for_user(uuid=uuid, user=user)
        if session is None:
            return None
        session.title = title
        session.save(update_fields=["title", "modified_at"])
        return session

    @classmethod
    def set_title_if_blank(cls, session: ChatSession, title: str) -> ChatSession:
        """Set a derived title on a brand-new session, idempotently.
        Subsequent turns on the same session won't overwrite a title
        the user has already curated (or that the first turn produced).
        """
        if session.title or not title:
            return session
        max_len = cls.model._meta.get_field("title").max_length
        session.title = title[:max_len]
        session.save(update_fields=["title", "modified_at"])
        return session
