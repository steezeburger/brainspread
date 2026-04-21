import logging
from typing import Any, Dict, Iterator, List

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError, AIUsage
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SendMessageForm
from ..repositories import (
    AIModelRepository,
    ChatMessageRepository,
    ChatSessionRepository,
)
from .send_message_command import (
    BRAINSPREAD_SYSTEM_PROMPT,
    SendMessageCommand,
    SendMessageCommandError,
)

logger = logging.getLogger(__name__)


class StreamSendMessageCommand(AbstractBaseCommand):
    """Send a chat message and yield incremental SSE-shaped events.

    Mirrors SendMessageCommand's persistence but streams text/thinking deltas
    back to the caller as they arrive and persists the assistant record once
    the stream completes.
    """

    def __init__(self, form: SendMessageForm) -> None:
        self.form = form

    def execute(self) -> Iterator[Dict[str, Any]]:
        super().execute()

        session = None
        user = self.form.cleaned_data["user"]
        model = self.form.cleaned_data["model"]
        provider_name = self.form.cleaned_data["provider_name"]

        try:
            message = self.form.cleaned_data["message"]
            api_key = self.form.cleaned_data["api_key"]
            session = self.form.cleaned_data.get("session_id")
            context_blocks = self.form.cleaned_data.get("context_blocks", [])

            if not session:
                session = ChatSessionRepository.create_session(user)

            formatted_message = SendMessageCommand._format_message_with_context(
                message, context_blocks
            )
            ChatMessageRepository.add_message(session, "user", formatted_message)

            messages: List[Dict[str, str]] = [
                {"role": msg.role, "content": msg.content}
                for msg in ChatMessageRepository.get_messages(session)
            ]

            service = AIServiceFactory.create_service(
                provider_name=provider_name,
                api_key=api_key,
                model=model,
            )
            tools = SendMessageCommand._get_web_search_tools(provider_name)

            yield {
                "type": "session",
                "session_id": str(session.uuid),
            }

            final_content = ""
            final_thinking = ""
            final_usage = AIUsage()

            for event in service.stream_message(
                messages, tools, system=BRAINSPREAD_SYSTEM_PROMPT
            ):
                etype = event.get("type")
                if etype == "text":
                    yield {"type": "text", "delta": event.get("delta", "")}
                elif etype == "thinking":
                    yield {"type": "thinking", "delta": event.get("delta", "")}
                elif etype == "done":
                    final_content = event.get("content", "") or ""
                    final_thinking = event.get("thinking") or ""
                    final_usage = event.get("usage") or AIUsage()

            ai_model = AIModelRepository.get_by_name(model)
            assistant_message = ChatMessageRepository.add_message(
                session,
                "assistant",
                final_content,
                ai_model=ai_model,
                thinking=final_thinking,
                usage=final_usage,
            )

            yield {
                "type": "done",
                "session_id": str(session.uuid),
                "message": SendMessageCommand._serialize_message(
                    assistant_message, ai_model
                ),
            }

        except (AIServiceError, AIServiceFactoryError) as e:
            logger.error(f"AI service error for user {user.id}: {str(e)}")
            if session:
                ai_model = AIModelRepository.get_by_name(model)
                error_message = (
                    f"Sorry, I'm experiencing technical difficulties: {str(e)}"
                )
                ChatMessageRepository.add_message(
                    session,
                    "assistant",
                    error_message,
                    ai_model=ai_model,
                )
            yield {"type": "error", "error": f"AI service error: {str(e)}"}
            raise SendMessageCommandError(f"AI service error: {str(e)}") from e

        except SendMessageCommandError:
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error in StreamSendMessageCommand for user {user.id}: {str(e)}"
            )
            yield {"type": "error", "error": "An unexpected error occurred."}
            raise SendMessageCommandError(
                f"An unexpected error occurred: {str(e)}"
            ) from e
