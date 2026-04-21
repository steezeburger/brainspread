import logging
from typing import Any, Dict, List, Optional

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError
from ai_chat.tools.web_search import WebSearchTools
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SendMessageForm
from ..repositories import (
    AIModelRepository,
    ChatMessageRepository,
    ChatSessionRepository,
)

logger = logging.getLogger(__name__)


# A stable system prompt gives providers that support prompt caching something
# worth caching. Keep it short but concrete.
BRAINSPREAD_SYSTEM_PROMPT = (
    "You are the assistant embedded in brainspread, a personal note-taking app"
    " where users capture thoughts as hierarchical blocks on daily pages."
    " Be concise, direct, and helpful. Format answers as markdown."
    " When the user attaches note blocks as context, prefer them over outside"
    " knowledge and cite specific items when relevant."
)


class SendMessageCommandError(Exception):
    """Custom exception for command errors"""

    pass


class SendMessageCommand(AbstractBaseCommand):
    def __init__(self, form: SendMessageForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        try:
            message = self.form.cleaned_data["message"]
            model = self.form.cleaned_data["model"]
            session = self.form.cleaned_data.get("session_id")
            context_blocks = self.form.cleaned_data.get("context_blocks", [])
            provider_name = self.form.cleaned_data["provider_name"]
            api_key = self.form.cleaned_data["api_key"]
            user = self.form.cleaned_data["user"]

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

            result = service.send_message(
                messages, tools, system=BRAINSPREAD_SYSTEM_PROMPT
            )

            ai_model = AIModelRepository.get_by_name(model)

            assistant_message = ChatMessageRepository.add_message(
                session,
                "assistant",
                result.content,
                ai_model=ai_model,
                thinking=result.thinking or "",
                usage=result.usage,
            )

            return {
                "response": result.content,
                "session_id": str(session.uuid),
                "message": self._serialize_message(assistant_message, ai_model),
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
            raise SendMessageCommandError(f"AI service error: {str(e)}") from e

        except SendMessageCommandError:
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error in SendMessageCommand for user {user.id}: {str(e)}"
            )
            raise SendMessageCommandError(
                f"An unexpected error occurred: {str(e)}"
            ) from e

    @staticmethod
    def _serialize_message(message, ai_model) -> Dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "thinking": message.thinking or None,
            "created_at": message.created_at.isoformat(),
            "usage": {
                "input_tokens": message.input_tokens,
                "output_tokens": message.output_tokens,
                "cache_creation_input_tokens": message.cache_creation_input_tokens,
                "cache_read_input_tokens": message.cache_read_input_tokens,
            },
            "ai_model": (
                {
                    "name": ai_model.name,
                    "display_name": ai_model.display_name,
                    "provider": ai_model.provider.name,
                }
                if ai_model
                else None
            ),
        }

    @staticmethod
    def _format_message_with_context(
        message: str, context_blocks: List[Dict]
    ) -> str:
        """Format the user message with context blocks if any are provided."""
        if not context_blocks:
            return message

        context_text_parts = []
        for block in context_blocks:
            content = block.get("content", "").strip()
            if content:
                block_type = block.get("block_type", "bullet")
                if block_type == "todo":
                    context_text_parts.append(f"☐ {content}")
                elif block_type == "done":
                    context_text_parts.append(f"☑ {content}")
                else:
                    context_text_parts.append(f"• {content}")

        if not context_text_parts:
            return message

        context_section = "\n".join(context_text_parts)
        return f"""**Context from my notes:**
{context_section}

**My question:**
{message}"""

    @staticmethod
    def _get_web_search_tools(
        provider_name: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Get web search tools configuration for the specified provider."""
        if provider_name == "anthropic":
            return [WebSearchTools.anthropic_web_search()]
        elif provider_name == "openai":
            return [WebSearchTools.openai_web_search()]
        elif provider_name == "google":
            return [WebSearchTools.google_search()]

        return None
