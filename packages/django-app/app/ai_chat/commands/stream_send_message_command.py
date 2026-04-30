import logging
from typing import Any, Dict, Iterator, List

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError, AIUsage
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SendMessageForm
from ..models import PendingToolApproval
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


class PendingApprovalPersistError(Exception):
    """Raised when we cannot snapshot a tool-approval pause to the database."""


class StreamSendMessageCommand(AbstractBaseCommand):
    """Send a chat message and yield incremental SSE-shaped events.

    Mirrors SendMessageCommand's persistence but streams text/thinking deltas
    back to the caller as they arrive and persists the assistant record once
    the stream completes.
    """

    def __init__(self, form: SendMessageForm) -> None:
        self.form = form

    @staticmethod
    def _persist_pending_approval(
        *,
        session,
        ai_model,
        provider_name: str,
        pending,
        partial_text: str,
        partial_thinking: str,
        tool_events: List[Dict[str, Any]],
        usage: AIUsage,
        enable_notes_tools: bool,
        enable_notes_write_tools: bool,
        auto_approve_notes_writes: bool,
        enable_web_search: bool,
    ) -> PendingToolApproval:
        try:
            return PendingToolApproval.objects.create(
                session=session,
                ai_model=ai_model,
                provider_name=provider_name,
                system_prompt=BRAINSPREAD_SYSTEM_PROMPT,
                messages_snapshot=pending.messages,
                assistant_blocks=pending.assistant_blocks,
                tool_uses=pending.tool_uses,
                tool_events=list(tool_events or []),
                partial_text=partial_text or "",
                partial_thinking=partial_thinking or "",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
                enable_notes_tools=enable_notes_tools,
                enable_notes_write_tools=enable_notes_write_tools,
                auto_approve_notes_writes=auto_approve_notes_writes,
                enable_web_search=enable_web_search,
            )
        except Exception as e:
            raise PendingApprovalPersistError(str(e)) from e

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
            attached_assets = self.form.cleaned_data.get("asset_uuids") or []
            ChatMessageRepository.add_message(
                session,
                "user",
                formatted_message,
                attachments=SendMessageCommand._serialize_attachments(attached_assets),
            )

            messages = SendMessageCommand._build_messages_with_images(session)

            service = AIServiceFactory.create_service(
                provider_name=provider_name,
                api_key=api_key,
                model=model,
            )
            enable_notes_tools = self.form.cleaned_data.get("enable_notes_tools")
            enable_notes_write_tools = self.form.cleaned_data.get(
                "enable_notes_write_tools"
            )
            auto_approve_notes_writes = self.form.cleaned_data.get(
                "auto_approve_notes_writes"
            )
            enable_web_search = self.form.cleaned_data.get("enable_web_search", True)
            tools, tool_executor = SendMessageCommand._build_tools(
                provider_name,
                user,
                enable_notes_tools,
                enable_web_search,
                enable_notes_write_tools=enable_notes_write_tools,
                auto_approve_notes_writes=auto_approve_notes_writes,
            )

            yield {
                "type": "session",
                "session_id": str(session.uuid),
            }

            final_content = ""
            final_thinking = ""
            final_usage = AIUsage()
            final_tool_events: List[Dict[str, Any]] = []
            final_pending_approval = None

            for event in service.stream_message(
                messages,
                tools,
                system=BRAINSPREAD_SYSTEM_PROMPT,
                tool_executor=tool_executor,
            ):
                etype = event.get("type")
                if etype == "text":
                    yield {"type": "text", "delta": event.get("delta", "")}
                elif etype == "thinking":
                    yield {"type": "thinking", "delta": event.get("delta", "")}
                elif etype == "tool_use":
                    yield {
                        "type": "tool_use",
                        "tool_use_id": event.get("tool_use_id", ""),
                        "name": event.get("name", ""),
                        "input": event.get("input", {}),
                    }
                elif etype == "tool_result":
                    yield {
                        "type": "tool_result",
                        "tool_use_id": event.get("tool_use_id", ""),
                        "name": event.get("name", ""),
                        "result": event.get("result", {}),
                    }
                elif etype == "approval_required":
                    # Intermediate event — the real persistence happens when
                    # the service's final `done` carries pending_approval.
                    continue
                elif etype == "done":
                    final_content = event.get("content", "") or ""
                    final_thinking = event.get("thinking") or ""
                    final_usage = event.get("usage") or AIUsage()
                    final_tool_events = event.get("tool_events") or []
                    final_pending_approval = event.get("pending_approval")

            ai_model = AIModelRepository.get_by_name(model)

            if final_pending_approval is not None:
                approval = self._persist_pending_approval(
                    session=session,
                    ai_model=ai_model,
                    provider_name=provider_name,
                    pending=final_pending_approval,
                    partial_text=final_content,
                    partial_thinking=final_thinking,
                    tool_events=final_tool_events,
                    usage=final_usage,
                    enable_notes_tools=bool(enable_notes_tools),
                    enable_notes_write_tools=bool(enable_notes_write_tools),
                    auto_approve_notes_writes=bool(auto_approve_notes_writes),
                    enable_web_search=bool(enable_web_search),
                )
                yield {
                    "type": "approval_required",
                    "session_id": str(session.uuid),
                    "approval_id": str(approval.uuid),
                    "tool_uses": approval.tool_uses,
                    "partial_text": approval.partial_text,
                    "partial_thinking": approval.partial_thinking,
                    "tool_events": approval.tool_events,
                }
                return

            assistant_message = ChatMessageRepository.add_message(
                session,
                "assistant",
                final_content,
                ai_model=ai_model,
                thinking=final_thinking,
                usage=final_usage,
                tool_events=final_tool_events,
            )

            yield {
                "type": "done",
                "session_id": str(session.uuid),
                "message": SendMessageCommand._serialize_message(
                    assistant_message, ai_model
                ),
            }

        except PendingApprovalPersistError as e:
            logger.error(f"Failed to persist pending approval: {e}")
            yield {
                "type": "error",
                "error": "Failed to record pending approval. Please retry.",
            }
            raise SendMessageCommandError(str(e)) from e

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
