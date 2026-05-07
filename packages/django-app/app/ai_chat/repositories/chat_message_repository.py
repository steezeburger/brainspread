from typing import Any, Dict, List, Optional

from common.repositories.base_repository import BaseRepository
from core.models import User

from ..models import AIModel, ChatMessage, ChatSession
from ..services.base_ai_service import AIUsage


class ChatMessageRepository(BaseRepository):
    model = ChatMessage

    @classmethod
    def get_by_uuid(cls, uuid: str) -> Optional[ChatMessage]:
        try:
            return cls.model.objects.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_for_user_with_session(cls, uuid: str, user: User) -> Optional[ChatMessage]:
        """Look up a message scoped to its owning user, with session
        and ai_model prefetched. Used by FollowMessageView to authorize
        and render in one round trip.
        """
        try:
            return cls.model.objects.select_related(
                "session", "ai_model__provider"
            ).get(uuid=uuid, session__user=user)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def first_user_message(cls, session: ChatSession) -> Optional[ChatMessage]:
        return session.messages.filter(role="user").order_by("created_at").first()

    @classmethod
    def first_content_match_in_session(
        cls, session: ChatSession, search: str
    ) -> Optional[ChatMessage]:
        return (
            session.messages.filter(content__icontains=search)
            .order_by("created_at")
            .first()
        )

    @classmethod
    def count_for_session(cls, session: ChatSession) -> int:
        return session.messages.count()

    @classmethod
    def mark_streaming_as_error(cls, uuid: str) -> None:
        """Atomic: only flip 'streaming' rows to 'error'. Used when a
        follower decides the worker thread is dead so we don't race a
        late successful finalize."""
        cls.model.objects.filter(uuid=uuid, status=ChatMessage.STATUS_STREAMING).update(
            status=ChatMessage.STATUS_ERROR
        )

    @classmethod
    def add_message(
        cls,
        session: ChatSession,
        role: str,
        content: str,
        ai_model: Optional[AIModel] = None,
        thinking: str = "",
        usage: Optional[AIUsage] = None,
        tool_events: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        status: Optional[str] = None,
    ) -> ChatMessage:
        fields = {
            "session": session,
            "role": role,
            "content": content,
            "ai_model": ai_model,
            "thinking": thinking or "",
            "tool_events": tool_events or [],
            "attachments": attachments or [],
        }
        if status is not None:
            fields["status"] = status
        if usage is not None:
            fields.update(
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                }
            )
        return cls.model.objects.create(**fields)

    @classmethod
    def get_messages(cls, session: ChatSession) -> List[ChatMessage]:
        return list(session.messages.order_by("created_at"))

    @classmethod
    def messages_for_session_with_models(
        cls, session: ChatSession
    ) -> List[ChatMessage]:
        """Same as get_messages but eager-loads the ai_model + provider
        so a per-message serializer can render the provider name
        without N+1ing the chat history endpoint."""
        return list(
            session.messages.select_related("ai_model__provider").order_by("created_at")
        )
