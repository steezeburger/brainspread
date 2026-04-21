from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Protocol


class AIServiceError(Exception):
    """Base exception for AI service errors"""

    pass


class ToolExecutor(Protocol):
    """Callable that runs a custom (client-side) tool and returns a JSON-
    serialisable result dict. Services use this to complete a tool-use loop
    when the model asks for a tool that isn't provider-native."""

    def is_known(self, name: str) -> bool: ...

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]: ...


@dataclass
class AIUsage:
    """Token usage for a single AI service call.

    All fields default to 0 so services that don't surface a given counter
    still produce a valid record.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    # Anthropic-only: tokens written to the prompt cache on this request.
    cache_creation_input_tokens: int = 0
    # Anthropic + OpenAI: tokens served from cache rather than the live prompt.
    cache_read_input_tokens: int = 0


@dataclass
class AIServiceResult:
    """Structured response from an AI provider."""

    content: str
    thinking: Optional[str] = None
    usage: AIUsage = field(default_factory=AIUsage)


class BaseAIService(ABC):
    """Abstract base class for AI service implementations"""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def send_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> AIServiceResult:
        """
        Send messages to AI service and return the response.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            tools: Optional list of tools/functions to make available to the model
            system: Optional system prompt. Providers that support a dedicated
                system slot should mark it with cache_control where possible.
            tool_executor: Optional callback that runs client-side tools and
                returns results so the service can complete the tool-use loop.

        Returns:
            AIServiceResult: Structured result containing the assistant text,
                optional thinking trace, and token usage.

        Raises:
            AIServiceError: If the API call fails
        """
        pass

    def stream_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream the assistant response as incremental events.

        Each yielded dict has a `type` field and type-specific payload:
          - {"type": "text", "delta": "..."}
          - {"type": "thinking", "delta": "..."}
          - {"type": "done", "content": str, "thinking": Optional[str],
             "usage": AIUsage}

        The default implementation buffers `send_message` into a single
        `done` event so providers without native streaming still work.
        Subclasses should override for true streaming.
        """
        result = self.send_message(
            messages, tools, system=system, tool_executor=tool_executor
        )
        if result.content:
            yield {"type": "text", "delta": result.content}
        if result.thinking:
            yield {"type": "thinking", "delta": result.thinking}
        yield {
            "type": "done",
            "content": result.content,
            "thinking": result.thinking,
            "usage": result.usage,
        }

    @abstractmethod
    def validate_api_key(self) -> bool:
        """
        Validate the API key by making a test call.

        Returns:
            bool: True if API key is valid, False otherwise
        """
        pass

    def validate_messages(self, messages: List[Dict[str, str]]) -> None:
        """
        Validate message format before sending to AI service.

        Args:
            messages: List of message dictionaries

        Raises:
            AIServiceError: If message format is invalid
        """
        for msg in messages:
            if "role" not in msg or "content" not in msg:
                raise AIServiceError(
                    "Invalid message format: missing 'role' or 'content'"
                )
            if msg["role"] not in ["user", "assistant", "system"]:
                raise AIServiceError(f"Invalid role: {msg['role']}")
