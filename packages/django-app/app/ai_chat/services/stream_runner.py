"""Background-thread runner for assistant message streaming so the
in-flight LLM call survives a client disconnect (page reload, network
blip, etc).

The thread iterates the AI service stream and writes incremental
state to the assistant ChatMessage row in the database. The HTTP
response (and any later /messages/<uuid>/follow/ request) tails that
row by polling, computing deltas against what it last yielded.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from django.db import close_old_connections

from ..models import ChatMessage
from ..services.base_ai_service import AIUsage

logger = logging.getLogger(__name__)

# Cap how long a tail loop will wait for new content before deciding
# the worker has died (worker thread killed by gunicorn timeout, OOM,
# etc.). Long-running responses can pause for tool execution, so the
# threshold needs to be generous; 90s is well past Anthropic's longest
# typical turn while still bounding the worst case.
STALE_THRESHOLD_SECONDS = 90.0

# Tail-loop poll cadence. Tight enough that a token arriving in the
# DB renders within a frame on fast networks; loose enough to not hit
# the DB more than ~10x/sec per active follower.
POLL_INTERVAL_SECONDS = 0.1


@dataclass
class StreamRunnerInputs:
    """Everything the worker thread needs to drive the AI service.

    The fields are split across this dataclass instead of being
    keyword-only constructor args to keep the call site at the command
    layer readable; the command was already juggling nine variables.
    """

    service: Any
    messages: List[Dict[str, Any]]
    tools: Any
    tool_executor: Any
    system: str
    response_format: Optional[Dict[str, Any]] = None


def run_stream_in_thread(
    *,
    assistant_message: ChatMessage,
    inputs: StreamRunnerInputs,
    on_done: Optional[Any] = None,
    on_approval: Optional[Any] = None,
    on_error: Optional[Any] = None,
) -> threading.Thread:
    """Spawn the worker thread that drives the AI service iteration.

    The thread owns the assistant_message row's lifecycle: it appends
    deltas to content/thinking, replaces tool_events, and finally
    transitions the row to status='complete' or 'error'. The
    on_* callbacks are invoked from the worker thread (so they need
    to be thread-safe) and are intended for hooks that the inline
    generator can't satisfy on its own — e.g. persisting a pending
    tool approval.
    """
    thread = threading.Thread(
        target=_run_worker,
        kwargs={
            "assistant_message_id": assistant_message.id,
            "inputs": inputs,
            "on_done": on_done,
            "on_approval": on_approval,
            "on_error": on_error,
        },
        name=f"stream-runner-{assistant_message.uuid}",
        daemon=True,
    )
    thread.start()
    return thread


def _run_worker(
    *,
    assistant_message_id: int,
    inputs: StreamRunnerInputs,
    on_done: Optional[Any],
    on_approval: Optional[Any],
    on_error: Optional[Any],
) -> None:
    """Worker entry point. Runs in its own thread so a client
    disconnect doesn't take down the LLM call."""
    try:
        msg = ChatMessage.objects.get(id=assistant_message_id)
    except ChatMessage.DoesNotExist:
        logger.error(
            "stream_runner: assistant message %s vanished before worker start",
            assistant_message_id,
        )
        close_old_connections()
        return

    accumulated_text = ""
    accumulated_thinking = ""
    accumulated_tool_events: List[Dict[str, Any]] = []
    final_usage = AIUsage()
    final_pending_approval = None

    try:
        for event in inputs.service.stream_message(
            inputs.messages,
            inputs.tools,
            system=inputs.system,
            tool_executor=inputs.tool_executor,
            response_format=inputs.response_format,
        ):
            etype = event.get("type")
            if etype == "text":
                delta = event.get("delta", "") or ""
                if delta:
                    accumulated_text += delta
                    msg.content = accumulated_text
                    msg.save(update_fields=["content", "modified_at"])
            elif etype == "thinking":
                delta = event.get("delta", "") or ""
                if delta:
                    accumulated_thinking += delta
                    msg.thinking = accumulated_thinking
                    msg.save(update_fields=["thinking", "modified_at"])
            elif etype == "tool_use":
                accumulated_tool_events.append(
                    {
                        "type": "tool_use",
                        "tool_use_id": event.get("tool_use_id", ""),
                        "name": event.get("name", ""),
                        "input": event.get("input", {}),
                    }
                )
                msg.tool_events = list(accumulated_tool_events)
                msg.save(update_fields=["tool_events", "modified_at"])
            elif etype == "tool_result":
                accumulated_tool_events.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": event.get("tool_use_id", ""),
                        "name": event.get("name", ""),
                        "result": event.get("result", {}),
                    }
                )
                msg.tool_events = list(accumulated_tool_events)
                msg.save(update_fields=["tool_events", "modified_at"])
            elif etype == "approval_required":
                # Intermediate event — final state arrives in `done`.
                continue
            elif etype == "done":
                accumulated_text = event.get("content", accumulated_text) or ""
                accumulated_thinking = event.get("thinking", accumulated_thinking) or ""
                final_usage = event.get("usage") or AIUsage()
                done_tool_events = event.get("tool_events")
                if done_tool_events:
                    accumulated_tool_events = list(done_tool_events)
                final_pending_approval = event.get("pending_approval")

        if final_pending_approval is not None and on_approval is not None:
            # Tool approval pause. The hook owns the message's final
            # state — typically it persists the approval snapshot and
            # deletes this stub row so the resume flow can re-create
            # the assistant message from scratch (the existing
            # resume_approval_command path expects no assistant
            # message to exist while paused). Don't run _finalize here;
            # we'd race the deletion or stomp on whatever the hook
            # decided to do.
            on_approval(
                assistant_message=msg,
                pending=final_pending_approval,
                partial_text=accumulated_text,
                partial_thinking=accumulated_thinking,
                tool_events=accumulated_tool_events,
                usage=final_usage,
            )
            return

        _finalize(
            msg,
            content=accumulated_text,
            thinking=accumulated_thinking,
            tool_events=accumulated_tool_events,
            usage=final_usage,
            status=ChatMessage.STATUS_COMPLETE,
        )
        if on_done is not None:
            on_done(assistant_message=msg)

    except Exception as e:  # noqa: BLE001 — we want everything here
        logger.error(
            "stream_runner: error during stream for message %s: %s",
            assistant_message_id,
            e,
        )
        # Persist whatever we accumulated so the user at least sees
        # the partial response on reload.
        try:
            error_text = (
                accumulated_text or "An error occurred while generating the response."
            )
            _finalize(
                msg,
                content=error_text,
                thinking=accumulated_thinking,
                tool_events=accumulated_tool_events,
                usage=final_usage,
                status=ChatMessage.STATUS_ERROR,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "stream_runner: failed to write error state for %s",
                assistant_message_id,
            )
        if on_error is not None:
            try:
                on_error(assistant_message=msg, error=e)
            except Exception:  # noqa: BLE001
                logger.exception("stream_runner: on_error hook raised")
    finally:
        close_old_connections()


def _finalize(
    msg: ChatMessage,
    *,
    content: str,
    thinking: str,
    tool_events: List[Dict[str, Any]],
    usage: AIUsage,
    status: str,
) -> None:
    msg.content = content or ""
    msg.thinking = thinking or ""
    msg.tool_events = list(tool_events or [])
    msg.input_tokens = usage.input_tokens
    msg.output_tokens = usage.output_tokens
    msg.cache_creation_input_tokens = usage.cache_creation_input_tokens
    msg.cache_read_input_tokens = usage.cache_read_input_tokens
    msg.status = status
    msg.save(
        update_fields=[
            "content",
            "thinking",
            "tool_events",
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "status",
            "modified_at",
        ]
    )


@dataclass
class FollowState:
    """Tracks what the tail loop has already shipped to the client so
    each poll only emits new content as a delta."""

    content_offset: int = 0
    thinking_offset: int = 0
    tool_events_count: int = 0
    last_modified_at: Any = None
    last_progress_wall_clock: float = field(default_factory=time.monotonic)


def follow_message(message_uuid: str) -> Iterator[Dict[str, Any]]:
    """Tail an assistant message row, yielding SSE-shaped events as
    new content arrives. Terminates on a non-streaming status, or
    when the row hasn't been touched for STALE_THRESHOLD_SECONDS
    (worker thread presumed dead).
    """
    state = FollowState()
    try:
        try:
            msg = ChatMessage.objects.get(uuid=message_uuid)
        except ChatMessage.DoesNotExist:
            yield {"type": "error", "error": "Message not found"}
            return

        # Emit anything already on the row before entering the poll
        # loop, so a client that connects after the worker has already
        # written tokens doesn't miss them.
        yield from _emit_progress(msg, state)

        while msg.status == ChatMessage.STATUS_STREAMING:
            time.sleep(POLL_INTERVAL_SECONDS)
            try:
                msg.refresh_from_db()
            except ChatMessage.DoesNotExist:
                yield {"type": "error", "error": "Message disappeared"}
                return

            advanced = False
            for event in _emit_progress(msg, state):
                advanced = True
                yield event
            if advanced:
                state.last_progress_wall_clock = time.monotonic()
            elif (
                time.monotonic() - state.last_progress_wall_clock
                > STALE_THRESHOLD_SECONDS
            ):
                # Worker died without finalizing. Promote the row to
                # 'error' so future viewers don't tail forever, and
                # surface the partial we have.
                ChatMessage.objects.filter(
                    pk=msg.pk, status=ChatMessage.STATUS_STREAMING
                ).update(status=ChatMessage.STATUS_ERROR)
                yield {
                    "type": "error",
                    "error": "Stream stopped responding.",
                }
                return

        # Final flush in case the worker wrote the terminal delta and
        # finalize() in the same save() — refresh_from_db above caught
        # both, but _emit_progress only yields if offsets advanced.
        for event in _emit_progress(msg, state):
            yield event

        if msg.status == ChatMessage.STATUS_ERROR:
            yield {
                "type": "error",
                "error": "Stream ended with an error.",
            }
        else:
            from ..commands.send_message_command import SendMessageCommand

            yield {
                "type": "done",
                "session_id": str(msg.session.uuid),
                "message": SendMessageCommand._serialize_message(msg, msg.ai_model),
            }
    finally:
        close_old_connections()


def _emit_progress(msg: ChatMessage, state: FollowState) -> Iterator[Dict[str, Any]]:
    """Yield deltas for any new content that's appeared on the row
    since the previous poll. Updates state in-place so the next call
    only ships incremental data."""
    content = msg.content or ""
    if len(content) > state.content_offset:
        delta = content[state.content_offset :]
        state.content_offset = len(content)
        yield {"type": "text", "delta": delta}
    elif len(content) < state.content_offset:
        # Content shrank (probably a final replacement when the worker
        # consolidated the message in finalize()). Reset and resend
        # the full content so the client sees the canonical version.
        state.content_offset = len(content)
        yield {"type": "text", "delta": "", "replace": content}

    thinking = msg.thinking or ""
    if len(thinking) > state.thinking_offset:
        delta = thinking[state.thinking_offset :]
        state.thinking_offset = len(thinking)
        yield {"type": "thinking", "delta": delta}

    tool_events = list(msg.tool_events or [])
    if len(tool_events) > state.tool_events_count:
        for event in tool_events[state.tool_events_count :]:
            etype = event.get("type")
            if etype == "tool_use":
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
        state.tool_events_count = len(tool_events)
