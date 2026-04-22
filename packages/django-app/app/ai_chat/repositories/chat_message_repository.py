from typing import Any, Dict, List, Optional

from common.repositories.base_repository import BaseRepository

from ..models import AIModel, ChatMessage, ChatSession
from ..services.base_ai_service import AIUsage


class ChatMessageRepository(BaseRepository):
    model = ChatMessage

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
    ) -> ChatMessage:
        fields = {
            "session": session,
            "role": role,
            "content": content,
            "ai_model": ai_model,
            "thinking": thinking or "",
            "tool_events": tool_events or [],
        }
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
