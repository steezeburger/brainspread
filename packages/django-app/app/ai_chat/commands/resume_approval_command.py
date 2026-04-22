"""Resume a paused tool-approval chat turn.

Loads a PendingToolApproval, applies the user's decisions, executes the
tool_uses the assistant requested (reads auto-approve, writes gated on the
decision map), and continues streaming the assistant response from the
provider. If the model then requests another write tool, the command
re-pauses by persisting a new PendingToolApproval in the same session.
"""

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError, AIUsage
from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ResumeApprovalForm
from ..models import PendingToolApproval
from ..repositories import AIModelRepository, ChatMessageRepository
from ..repositories.user_settings_repository import UserSettingsRepository
from .send_message_command import (
    BRAINSPREAD_SYSTEM_PROMPT,
    SendMessageCommand,
    SendMessageCommandError,
)
from .stream_send_message_command import PendingApprovalPersistError

logger = logging.getLogger(__name__)

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"


class ResumeApprovalCommand(AbstractBaseCommand):
    """Apply per-tool decisions to a paused chat turn and stream the rest."""

    def __init__(self, form: ResumeApprovalForm) -> None:
        self.form = form

    def execute(self) -> Iterator[Dict[str, Any]]:
        super().execute()

        approval: PendingToolApproval = self.form.cleaned_data["approval"]
        decisions: Dict[str, str] = self.form.cleaned_data["decisions"]
        user = self.form.cleaned_data["user"]
        session = approval.session

        if approval.status != PendingToolApproval.STATUS_PENDING:
            yield {
                "type": "error",
                "error": "This approval has already been resolved.",
            }
            return

        api_key = self._resolve_api_key(user, approval.provider_name)
        if not api_key:
            yield {
                "type": "error",
                "error": (
                    f"No API key configured for {approval.provider_name}."
                    " Please add it in settings."
                ),
            }
            return

        model_name = (approval.ai_model.name if approval.ai_model else None) or ""
        if not model_name:
            yield {
                "type": "error",
                "error": "The model for this pending approval is no longer available.",
            }
            return

        try:
            service = AIServiceFactory.create_service(
                provider_name=approval.provider_name,
                api_key=api_key,
                model=model_name,
            )
        except AIServiceFactoryError as e:
            yield {"type": "error", "error": f"AI service error: {e}"}
            return

        tool_executor = NotesToolExecutor(
            user, allow_writes=approval.enable_notes_write_tools
        )

        tool_results, executed_events = self._execute_paused_tools(
            approval.tool_uses, decisions, tool_executor
        )

        resume_tool_events = list(approval.tool_events or []) + executed_events

        resumed_messages = list(approval.messages_snapshot or [])
        resumed_messages.append(
            {"role": "assistant", "content": list(approval.assistant_blocks or [])}
        )
        resumed_messages.append({"role": "user", "content": tool_results})

        tools, _ = SendMessageCommand._build_tools(
            approval.provider_name,
            user,
            approval.enable_notes_tools,
            approval.enable_web_search,
            enable_notes_write_tools=approval.enable_notes_write_tools,
        )

        yield {
            "type": "session",
            "session_id": str(session.uuid),
        }
        # Replay previously-executed tool events so the UI can rebuild state
        # if the resume call comes from a fresh page load.
        for event in resume_tool_events:
            yield event

        final_content = approval.partial_text or ""
        final_thinking = approval.partial_thinking or ""
        final_usage = AIUsage(
            input_tokens=approval.input_tokens,
            output_tokens=approval.output_tokens,
            cache_creation_input_tokens=approval.cache_creation_input_tokens,
            cache_read_input_tokens=approval.cache_read_input_tokens,
        )
        final_tool_events: List[Dict[str, Any]] = list(resume_tool_events)
        final_pending_approval = None

        try:
            for event in service.stream_message(
                resumed_messages,
                tools,
                system=approval.system_prompt or BRAINSPREAD_SYSTEM_PROMPT,
                tool_executor=tool_executor,
            ):
                etype = event.get("type")
                if etype == "text":
                    final_content += event.get("delta", "") or ""
                    yield {"type": "text", "delta": event.get("delta", "")}
                elif etype == "thinking":
                    final_thinking += event.get("delta", "") or ""
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
                    continue
                elif etype == "done":
                    turn_content = event.get("content", "") or ""
                    turn_thinking = event.get("thinking") or ""
                    turn_usage = event.get("usage") or AIUsage()
                    turn_tool_events = event.get("tool_events") or []
                    # `final_content` / `final_thinking` were accumulated via
                    # deltas as we re-streamed; the `done` event's content is
                    # the full post-resume turn which we use to resolve any
                    # drift.
                    if turn_content:
                        final_content = (approval.partial_text or "") + turn_content
                    if turn_thinking:
                        final_thinking = (
                            approval.partial_thinking or ""
                        ) + turn_thinking
                    self._merge_usage(final_usage, turn_usage)
                    final_tool_events = resume_tool_events + list(turn_tool_events)
                    final_pending_approval = event.get("pending_approval")

        except AIServiceError as e:
            logger.error(f"Resume stream error for user {user.id}: {e}")
            yield {"type": "error", "error": f"AI service error: {e}"}
            raise SendMessageCommandError(str(e)) from e

        # We've completed at least one live round-trip; retire the original
        # approval regardless of whether another pause follows.
        approval.status = PendingToolApproval.STATUS_COMPLETED
        approval.save(update_fields=["status", "modified_at"])

        ai_model = approval.ai_model or AIModelRepository.get_by_name(model_name)

        if final_pending_approval is not None:
            try:
                next_approval = PendingToolApproval.objects.create(
                    session=session,
                    ai_model=ai_model,
                    provider_name=approval.provider_name,
                    system_prompt=approval.system_prompt or BRAINSPREAD_SYSTEM_PROMPT,
                    messages_snapshot=final_pending_approval.messages,
                    assistant_blocks=final_pending_approval.assistant_blocks,
                    tool_uses=final_pending_approval.tool_uses,
                    tool_events=final_tool_events,
                    partial_text=final_content,
                    partial_thinking=final_thinking,
                    input_tokens=final_usage.input_tokens,
                    output_tokens=final_usage.output_tokens,
                    cache_creation_input_tokens=final_usage.cache_creation_input_tokens,
                    cache_read_input_tokens=final_usage.cache_read_input_tokens,
                    enable_notes_tools=approval.enable_notes_tools,
                    enable_notes_write_tools=approval.enable_notes_write_tools,
                    enable_web_search=approval.enable_web_search,
                )
            except Exception as e:  # pragma: no cover - defensive
                raise PendingApprovalPersistError(str(e)) from e

            yield {
                "type": "approval_required",
                "session_id": str(session.uuid),
                "approval_id": str(next_approval.uuid),
                "tool_uses": next_approval.tool_uses,
                "partial_text": next_approval.partial_text,
                "partial_thinking": next_approval.partial_thinking,
                "tool_events": next_approval.tool_events,
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

    @staticmethod
    def _resolve_api_key(user, provider_name: str) -> Optional[str]:
        from ai_chat.models import AIProvider

        try:
            provider = AIProvider.objects.get(name__iexact=provider_name)
        except AIProvider.DoesNotExist:
            return None
        return UserSettingsRepository().get_api_key(user, provider)

    @staticmethod
    def _merge_usage(total: AIUsage, turn: AIUsage) -> None:
        total.input_tokens += turn.input_tokens
        total.output_tokens += turn.output_tokens
        total.cache_creation_input_tokens += turn.cache_creation_input_tokens
        total.cache_read_input_tokens += turn.cache_read_input_tokens

    @staticmethod
    def _execute_paused_tools(
        tool_uses: List[Dict[str, Any]],
        decisions: Dict[str, str],
        tool_executor: NotesToolExecutor,
    ):
        """Run each paused tool_use and build (tool_results, tool_events).

        Reads and approved writes call through to the executor. Rejected
        writes produce a result the model can reason about ("User declined...")
        without touching user data.
        """
        tool_results: List[Dict[str, Any]] = []
        tool_events: List[Dict[str, Any]] = []
        for tu in tool_uses:
            tu_id = tu.get("tool_use_id", "")
            name = tu.get("name", "")
            args = tu.get("input", {}) or {}
            requires_approval = bool(tu.get("requires_approval"))

            tool_events.append(
                {
                    "type": "tool_use",
                    "tool_use_id": tu_id,
                    "name": name,
                    "input": args,
                }
            )

            if requires_approval:
                decision = decisions.get(tu_id)
                if decision == DECISION_APPROVE:
                    result = tool_executor.execute(name, args)
                else:
                    result = {
                        "error": "User declined this tool call.",
                        "declined": True,
                    }
            else:
                result = tool_executor.execute(name, args)

            tool_events.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "name": name,
                    "result": result,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": json.dumps(result),
                }
            )

        return tool_results, tool_events
