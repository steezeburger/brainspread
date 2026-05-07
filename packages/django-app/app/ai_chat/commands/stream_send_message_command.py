import logging
from typing import Any, Dict, Iterator, List, Optional

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError, AIUsage
from ai_chat.services.stream_runner import (
    StreamRunnerInputs,
    follow_message,
    run_stream_in_thread,
)
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SendMessageForm
from ..models import ChatMessage, PendingToolApproval
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
        current_page_uuid: Optional[str] = None,
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
                current_page_uuid=current_page_uuid or "",
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
            response_format = self.form.cleaned_data.get("response_format")
            current_page_uuid = (
                self.form.cleaned_data.get("current_page_uuid") or ""
            ).strip() or None
            tools, tool_executor = SendMessageCommand._build_tools(
                provider_name,
                user,
                enable_notes_tools,
                enable_web_search,
                enable_notes_write_tools=enable_notes_write_tools,
                auto_approve_notes_writes=auto_approve_notes_writes,
                current_page_uuid=current_page_uuid,
            )

            ai_model = AIModelRepository.get_by_name(model)

            # Pre-create the assistant row in 'streaming' state so we
            # have a stable handle the worker thread can write into and
            # the client can reconnect to via /messages/<uuid>/follow/
            # after a reload.
            assistant_message = ChatMessageRepository.add_message(
                session,
                "assistant",
                "",
                ai_model=ai_model,
                status=ChatMessage.STATUS_STREAMING,
            )

            yield {
                "type": "session",
                "session_id": str(session.uuid),
                "assistant_message_uuid": str(assistant_message.uuid),
            }

            # Hook the approval flow back into the existing
            # PendingToolApproval persistence. The worker calls this
            # from its own thread, so we capture the small set of vars
            # it needs by closure rather than threading them through
            # follow_message.
            approval_holder: Dict[str, Any] = {}

            def _on_approval(
                *,
                assistant_message,
                pending,
                partial_text,
                partial_thinking,
                tool_events,
                usage,
            ):
                try:
                    approval = self._persist_pending_approval(
                        session=session,
                        ai_model=ai_model,
                        provider_name=provider_name,
                        pending=pending,
                        partial_text=partial_text,
                        partial_thinking=partial_thinking,
                        tool_events=tool_events,
                        usage=usage,
                        enable_notes_tools=bool(enable_notes_tools),
                        enable_notes_write_tools=bool(enable_notes_write_tools),
                        auto_approve_notes_writes=bool(auto_approve_notes_writes),
                        enable_web_search=bool(enable_web_search),
                        current_page_uuid=current_page_uuid,
                    )
                    approval_holder["approval"] = approval
                    # The PendingToolApproval row holds the canonical
                    # partial state for the approval pause; the
                    # pre-created assistant_message would otherwise
                    # double-record it and leave a stub message in the
                    # session that the resume flow doesn't expect.
                    # Delete the stub so resume_approval_command stays
                    # the sole creator of the assistant message.
                    assistant_message.delete()
                except PendingApprovalPersistError as e:
                    approval_holder["error"] = e
                    logger.error("Failed to persist pending approval: %s", e)

            run_stream_in_thread(
                assistant_message=assistant_message,
                inputs=StreamRunnerInputs(
                    service=service,
                    messages=messages,
                    tools=tools,
                    tool_executor=tool_executor,
                    system=BRAINSPREAD_SYSTEM_PROMPT,
                    response_format=response_format,
                ),
                on_approval=_on_approval,
            )

            # Tail the message row, yielding deltas to the client. If
            # the client disconnects mid-stream, the worker thread
            # keeps writing and the next follow request picks up where
            # we left off. The follow generator handles the terminal
            # transition; we only need to substitute approval_required
            # for done/error when the worker tripped an approval
            # (the hook deletes the stub message, so follow_message
            # surfaces that as a "Message disappeared" error which
            # we then mask).
            for event in follow_message(str(assistant_message.uuid)):
                etype = event.get("type")
                if etype in ("done", "error") and approval_holder.get("approval"):
                    approval = approval_holder["approval"]
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
                if etype == "done":
                    event["session_id"] = str(session.uuid)
                yield event

            if approval_holder.get("error") is not None:
                raise approval_holder["error"]

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
