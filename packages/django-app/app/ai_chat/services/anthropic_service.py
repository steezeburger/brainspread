import base64
import json
import logging
from typing import Any, Dict, Iterator, List, Optional

import anthropic

from .base_ai_service import (
    AIServiceError,
    AIServiceResult,
    AIUsage,
    BaseAIService,
    PendingApproval,
    ToolExecutor,
)

logger = logging.getLogger(__name__)


# Claude models that support extended thinking. Keep this list conservative —
# enabling `thinking` on a model that doesn't support it raises at the API.
THINKING_CAPABLE_MODEL_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)

# Subset that accepts `thinking: {type: "adaptive"}`. Haiku 4.5 supports
# extended thinking but only in `enabled` mode — adaptive returns a 400.
ADAPTIVE_THINKING_CAPABLE_MODEL_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)

# Budget for `thinking: {type: "enabled"}` — must be strictly less than
# max_tokens on the request.
ENABLED_THINKING_BUDGET_TOKENS = 4096

# Models that accept `output_config.effort`. Sending it to Haiku 4.5 (or older
# non-4.6 models) returns a 400.
EFFORT_CAPABLE_MODEL_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)

DEFAULT_MAX_TOKENS = 8192

# Safety net for custom tool loops: the model shouldn't be able to spin
# us indefinitely even if it keeps requesting tool calls.
MAX_TOOL_ITERATIONS = 5


class AnthropicServiceError(AIServiceError):
    """Custom exception for Anthropic service errors"""

    pass


def _serialize_web_search_content(content: Any) -> Any:
    """Round-trip a web_search_tool_result.content payload back to dict form.

    The SDK returns either a list of result objects (each with type, url,
    title, encrypted_content, page_age) or an error object with a code.
    Either shape needs to come back as JSON-friendly dicts so the next
    messages.create round-trip accepts the assistant turn verbatim.
    """
    if content is None:
        return []
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        serialized: List[Dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict):
                serialized.append(item)
                continue
            item_type = getattr(item, "type", None)
            if item_type == "web_search_result":
                serialized.append(
                    {
                        "type": "web_search_result",
                        "url": getattr(item, "url", "") or "",
                        "title": getattr(item, "title", "") or "",
                        "encrypted_content": getattr(item, "encrypted_content", "")
                        or "",
                        "page_age": getattr(item, "page_age", None),
                    }
                )
            elif item_type == "web_search_tool_result_error":
                serialized.append(
                    {
                        "type": "web_search_tool_result_error",
                        "error_code": getattr(item, "error_code", "") or "",
                    }
                )
            else:
                serialized.append(
                    {
                        "type": item_type or "unknown",
                        "raw": str(item),
                    }
                )
        return serialized
    # Single error object (not wrapped in a list)
    err_type = getattr(content, "type", None)
    if err_type == "web_search_tool_result_error":
        return {
            "type": "web_search_tool_result_error",
            "error_code": getattr(content, "error_code", "") or "",
        }
    return {"raw": str(content)}


class AnthropicService(BaseAIService):
    def __init__(self, api_key: str, model: str = "claude-opus-4-7") -> None:
        super().__init__(api_key, model)
        try:
            self.client = anthropic.Anthropic(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            raise AnthropicServiceError(
                f"Failed to initialize Anthropic client: {e}"
            ) from e

    def _supports_thinking(self) -> bool:
        return self.model.startswith(THINKING_CAPABLE_MODEL_PREFIXES)

    def _supports_adaptive_thinking(self) -> bool:
        return self.model.startswith(ADAPTIVE_THINKING_CAPABLE_MODEL_PREFIXES)

    def _supports_effort(self) -> bool:
        return self.model.startswith(EFFORT_CAPABLE_MODEL_PREFIXES)

    def send_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AIServiceResult:
        try:
            self.validate_messages(messages)
            kwargs = self._build_kwargs(messages, tools, system, response_format)

            text_parts: List[str] = []
            thinking_parts: List[str] = []
            total_usage = AIUsage()
            tool_events: List[Dict[str, Any]] = []
            pending_approval: Optional[PendingApproval] = None

            for _ in range(MAX_TOOL_ITERATIONS + 1):
                response = self.client.messages.create(**kwargs)
                self._accumulate_usage(total_usage, response)

                for block in response.content or []:
                    block_type = getattr(block, "type", None)
                    if block_type == "thinking":
                        thinking_text = getattr(block, "thinking", None)
                        if thinking_text:
                            thinking_parts.append(thinking_text)
                    elif block_type == "tool_use":
                        continue
                    elif getattr(block, "text", None):
                        text_parts.append(block.text)
                    else:
                        logger.debug(
                            f"Unknown Anthropic block type: {block_type} attrs: {getattr(block, '__dict__', block)}"
                        )

                if (
                    tool_executor is None
                    or getattr(response, "stop_reason", None) != "tool_use"
                ):
                    break

                custom_tool_uses = [
                    block
                    for block in response.content or []
                    if getattr(block, "type", None) == "tool_use"
                    and tool_executor.is_known(getattr(block, "name", ""))
                ]
                if not custom_tool_uses:
                    break

                # The Anthropic API requires tool_result for EVERY tool_use in
                # a turn, so we can't partially execute — if any tool in this
                # turn needs approval, the whole turn pauses and resume runs
                # them all (reads auto, writes per user decision).
                needs_approval = any(
                    tool_executor.requires_approval(getattr(tu, "name", ""))
                    for tu in custom_tool_uses
                )
                if needs_approval:
                    assistant_blocks = [
                        self._serialize_block(b) for b in response.content or []
                    ]
                    pending_tool_uses = [
                        {
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "input": getattr(tu, "input", {}) or {},
                            "requires_approval": tool_executor.requires_approval(
                                getattr(tu, "name", "")
                            ),
                        }
                        for tu in custom_tool_uses
                    ]
                    pending_approval = PendingApproval(
                        messages=list(kwargs["messages"]),
                        assistant_blocks=assistant_blocks,
                        tool_uses=pending_tool_uses,
                    )
                    break

                for tu in custom_tool_uses:
                    tool_events.append(
                        {
                            "type": "tool_use",
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "input": getattr(tu, "input", {}) or {},
                        }
                    )

                kwargs["messages"].append(
                    {
                        "role": "assistant",
                        "content": [
                            self._serialize_block(b) for b in response.content or []
                        ],
                    }
                )
                tool_results: List[Dict[str, Any]] = []
                for tu in custom_tool_uses:
                    result = tool_executor.execute(
                        getattr(tu, "name", ""), getattr(tu, "input", {}) or {}
                    )
                    tool_events.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "result": result,
                        }
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(tu, "id", ""),
                            "content": json.dumps(result),
                        }
                    )
                kwargs["messages"].append({"role": "user", "content": tool_results})

            if not text_parts:
                logger.warning(
                    "No text content found in Anthropic response after tool loop"
                )
                content = (
                    "I apologize, but I encountered an issue processing the response."
                    " Please try again."
                )
            else:
                content = "\n".join(text_parts)

            thinking = "\n\n".join(thinking_parts) if thinking_parts else None

            return AIServiceResult(
                content=content,
                thinking=thinking,
                usage=total_usage,
                tool_events=tool_events,
                pending_approval=pending_approval,
            )

        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            if isinstance(e, AnthropicServiceError):
                raise
            raise AnthropicServiceError(f"Anthropic API call failed: {str(e)}") from e

    @staticmethod
    def _serialize_block(block: Any) -> Dict[str, Any]:
        """Serialize a response content block back to the dict shape the API accepts.

        Handles every block type Anthropic can emit on an assistant turn,
        including server-side tool blocks (web_search). Replaying the
        assistant turn verbatim is required when we send tool_results back
        for our custom tools — the API rejects the next request if any
        block is missing its identifying fields (e.g. server_tool_use.id).
        """
        block_type = getattr(block, "type", None)
        if block_type == "text":
            return {"type": "text", "text": getattr(block, "text", "") or ""}
        if block_type == "thinking":
            return {
                "type": "thinking",
                "thinking": getattr(block, "thinking", "") or "",
                "signature": getattr(block, "signature", "") or "",
            }
        if block_type == "redacted_thinking":
            return {
                "type": "redacted_thinking",
                "data": getattr(block, "data", "") or "",
            }
        if block_type == "tool_use":
            return {
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            }
        if block_type == "server_tool_use":
            return {
                "type": "server_tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            }
        if block_type == "web_search_tool_result":
            return {
                "type": "web_search_tool_result",
                "tool_use_id": getattr(block, "tool_use_id", ""),
                "content": _serialize_web_search_content(
                    getattr(block, "content", None)
                ),
            }
        return {"type": block_type or "text", "text": str(block)}

    @staticmethod
    def _accumulate_usage(total: AIUsage, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        total.input_tokens += getattr(usage, "input_tokens", 0) or 0
        total.output_tokens += getattr(usage, "output_tokens", 0) or 0
        total.cache_creation_input_tokens += (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        total.cache_read_input_tokens += (
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )

    def stream_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        try:
            self.validate_messages(messages)
            kwargs = self._build_kwargs(messages, tools, system, response_format)

            content_parts: List[str] = []
            thinking_parts: List[str] = []
            total_usage = AIUsage()
            tool_events: List[Dict[str, Any]] = []
            pending_approval: Optional[PendingApproval] = None

            for _ in range(MAX_TOOL_ITERATIONS + 1):
                turn_text, turn_thinking, turn_usage, final_message = (
                    yield from self._stream_single_turn(kwargs, tool_executor)
                )
                if turn_text:
                    content_parts.append(turn_text)
                if turn_thinking:
                    thinking_parts.append(turn_thinking)
                self._merge_usage(total_usage, turn_usage)

                stop_reason = getattr(final_message, "stop_reason", None)
                if tool_executor is None or stop_reason != "tool_use":
                    break

                blocks = getattr(final_message, "content", None) or []
                custom_tool_uses = [
                    b
                    for b in blocks
                    if getattr(b, "type", None) == "tool_use"
                    and tool_executor.is_known(getattr(b, "name", ""))
                ]
                if not custom_tool_uses:
                    break

                needs_approval = any(
                    tool_executor.requires_approval(getattr(tu, "name", ""))
                    for tu in custom_tool_uses
                )
                if needs_approval:
                    assistant_blocks = [self._serialize_block(b) for b in blocks]
                    pending_tool_uses = [
                        {
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "input": getattr(tu, "input", {}) or {},
                            "requires_approval": tool_executor.requires_approval(
                                getattr(tu, "name", "")
                            ),
                        }
                        for tu in custom_tool_uses
                    ]
                    pending_approval = PendingApproval(
                        messages=list(kwargs["messages"]),
                        assistant_blocks=assistant_blocks,
                        tool_uses=pending_tool_uses,
                    )
                    yield {
                        "type": "approval_required",
                        "tool_uses": pending_tool_uses,
                    }
                    break

                for tu in custom_tool_uses:
                    tool_events.append(
                        {
                            "type": "tool_use",
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "input": getattr(tu, "input", {}) or {},
                        }
                    )
                    yield tool_events[-1]

                kwargs["messages"].append(
                    {
                        "role": "assistant",
                        "content": [self._serialize_block(b) for b in blocks],
                    }
                )
                tool_results: List[Dict[str, Any]] = []
                for tu in custom_tool_uses:
                    result = tool_executor.execute(
                        getattr(tu, "name", ""), getattr(tu, "input", {}) or {}
                    )
                    tool_events.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(tu, "id", ""),
                            "name": getattr(tu, "name", ""),
                            "result": result,
                        }
                    )
                    yield tool_events[-1]
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(tu, "id", ""),
                            "content": json.dumps(result),
                        }
                    )
                kwargs["messages"].append({"role": "user", "content": tool_results})

            content = "".join(content_parts)
            thinking = "\n\n".join(thinking_parts) if thinking_parts else None

            yield {
                "type": "done",
                "content": content,
                "thinking": thinking,
                "usage": total_usage,
                "tool_events": tool_events,
                "pending_approval": pending_approval,
            }
        except Exception as e:
            logger.error(f"Anthropic streaming error: {e}")
            if isinstance(e, AnthropicServiceError):
                raise
            raise AnthropicServiceError(f"Anthropic streaming call failed: {e}") from e

    def _stream_single_turn(
        self,
        kwargs: Dict[str, Any],
        tool_executor: Optional[ToolExecutor] = None,
    ):
        """Stream one Anthropic turn, yielding text/thinking/tool_use deltas.

        Returns (turn_text, turn_thinking, turn_usage, final_message) via
        StopIteration value so the tool loop can decide whether to continue.

        For custom tools the model calls, we yield an early `tool_use`
        event as soon as content_block_start fires — the model signals the
        tool at block-start but the arguments stream in via later
        input_json_delta events. Emitting early makes the "running <tool>"
        UI appear the moment the model commits to calling the tool, not
        at turn-end.
        """
        text_parts: List[str] = []
        thinking_parts: List[str] = []
        input_tokens = 0
        output_tokens = 0
        cache_creation = 0
        cache_read = 0
        final_message: Any = None

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                event_type = getattr(event, "type", None)

                if event_type == "message_start":
                    start_usage = getattr(
                        getattr(event, "message", None), "usage", None
                    )
                    if start_usage is not None:
                        input_tokens = getattr(start_usage, "input_tokens", 0) or 0
                        cache_creation = (
                            getattr(start_usage, "cache_creation_input_tokens", 0) or 0
                        )
                        cache_read = (
                            getattr(start_usage, "cache_read_input_tokens", 0) or 0
                        )

                elif event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    block_type = getattr(block, "type", None)
                    if block_type == "tool_use":
                        tool_name = getattr(block, "name", "") or ""
                        # Only announce tools we can actually execute — an
                        # unknown tool would leave the "running" indicator
                        # stuck until some final event clears it.
                        if tool_executor is not None and tool_executor.is_known(
                            tool_name
                        ):
                            yield {
                                "type": "tool_use",
                                "tool_use_id": getattr(block, "id", "") or "",
                                "name": tool_name,
                                "input": {},
                            }

                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "") or ""
                        if text:
                            text_parts.append(text)
                            yield {"type": "text", "delta": text}
                    elif delta_type == "thinking_delta":
                        thinking = getattr(delta, "thinking", "") or ""
                        if thinking:
                            thinking_parts.append(thinking)
                            yield {"type": "thinking", "delta": thinking}

                elif event_type == "message_delta":
                    delta_usage = getattr(event, "usage", None)
                    if delta_usage is not None:
                        output_tokens = getattr(delta_usage, "output_tokens", 0) or 0

            final_message = stream.get_final_message()

        turn_usage = AIUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        )
        return (
            "".join(text_parts),
            "".join(thinking_parts),
            turn_usage,
            final_message,
        )

    @staticmethod
    def _merge_usage(total: AIUsage, turn: AIUsage) -> None:
        total.input_tokens += turn.input_tokens
        total.output_tokens += turn.output_tokens
        total.cache_creation_input_tokens += turn.cache_creation_input_tokens
        total.cache_read_input_tokens += turn.cache_read_input_tokens

    def _build_kwargs(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        system: Optional[str],
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        anthropic_messages: List[Dict[str, Any]] = []
        embedded_system: Optional[str] = None
        for msg in messages:
            if msg["role"] == "system":
                embedded_system = msg["content"]
                continue
            images = msg.get("images") or []
            if images:
                # Anthropic vision: content is a list of blocks. Image blocks
                # come BEFORE the text so the model has the picture in mind
                # when reading the prompt - matches Anthropic's documented
                # best practice.
                content_blocks: List[Dict[str, Any]] = []
                for img in images:
                    content_blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img["mime_type"],
                                "data": base64.b64encode(img["data"]).decode("ascii"),
                            },
                        }
                    )
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                anthropic_messages.append(
                    {"role": msg["role"], "content": content_blocks}
                )
            else:
                anthropic_messages.append(
                    {"role": msg["role"], "content": msg["content"]}
                )

        effective_system = system if system is not None else embedded_system
        thinking_enabled = self._supports_thinking()

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": anthropic_messages,
        }

        if effective_system:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": effective_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            kwargs["tools"] = tools
        if thinking_enabled:
            if self._supports_adaptive_thinking():
                # Adaptive thinking — Claude decides when and how much to
                # reason. `display: "summarized"` surfaces the reasoning
                # trace; the 4.7 default is "omitted" which would make
                # thinking blocks empty.
                kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
            else:
                # Haiku 4.5 supports extended thinking only in `enabled`
                # mode with an explicit budget (< max_tokens).
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": ENABLED_THINKING_BUDGET_TOKENS,
                }
        output_config: Dict[str, Any] = {}
        if self._supports_effort():
            output_config["effort"] = "high"
        if response_format and response_format.get("type") == "json_schema":
            # Anthropic's structured output: nest the JSON schema under
            # output_config.format. The `name`/`strict` fields from the
            # unified shape are OpenAI-only; Anthropic just needs the schema.
            output_config["format"] = {
                "type": "json_schema",
                "schema": response_format["schema"],
            }
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    @staticmethod
    def _extract_usage(response: Any) -> AIUsage:
        usage_obj = getattr(response, "usage", None)
        if usage_obj is None:
            return AIUsage()
        return AIUsage(
            input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
            cache_creation_input_tokens=(
                getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
            ),
            cache_read_input_tokens=(
                getattr(usage_obj, "cache_read_input_tokens", 0) or 0
            ),
        )

    def validate_api_key(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "Hi"}]
            response = self.client.messages.create(
                model=self.model, max_tokens=1, messages=test_messages
            )
            return response is not None
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            return False
