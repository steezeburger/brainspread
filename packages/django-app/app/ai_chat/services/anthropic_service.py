import logging
from typing import Any, Dict, List, Optional

import anthropic

from .base_ai_service import AIServiceError, AIServiceResult, AIUsage, BaseAIService

logger = logging.getLogger(__name__)


# Claude models that support extended thinking. Keep this list conservative —
# enabling `thinking` on a model that doesn't support it raises at the API.
THINKING_CAPABLE_MODEL_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)

# With thinking enabled Anthropic requires max_tokens > budget_tokens.
THINKING_BUDGET_TOKENS = 4000
DEFAULT_MAX_TOKENS = 2000
THINKING_MAX_TOKENS = 8000


class AnthropicServiceError(AIServiceError):
    """Custom exception for Anthropic service errors"""

    pass


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

    def send_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> AIServiceResult:
        try:
            self.validate_messages(messages)

            anthropic_messages = []
            # If a system prompt is embedded in messages (legacy callers), pull it out.
            embedded_system = None
            for msg in messages:
                if msg["role"] == "system":
                    embedded_system = msg["content"]
                else:
                    anthropic_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )

            effective_system = system if system is not None else embedded_system

            thinking_enabled = self._supports_thinking()

            kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": (
                    THINKING_MAX_TOKENS if thinking_enabled else DEFAULT_MAX_TOKENS
                ),
                "messages": anthropic_messages,
            }

            if effective_system:
                # Mark the system prompt as cacheable so repeated requests with
                # the same prompt pay the discounted cache-read rate.
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
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": THINKING_BUDGET_TOKENS,
                }

            response = self.client.messages.create(**kwargs)

            text_parts: List[str] = []
            thinking_parts: List[str] = []

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

            if not text_parts:
                logger.warning(
                    "No text content found in Anthropic response (%s blocks)",
                    len(response.content or []),
                )
                content = (
                    "I apologize, but I encountered an issue processing the response."
                    " Please try again."
                )
            else:
                content = "\n".join(text_parts)

            usage = self._extract_usage(response)
            thinking = "\n\n".join(thinking_parts) if thinking_parts else None

            return AIServiceResult(content=content, thinking=thinking, usage=usage)

        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            if isinstance(e, AnthropicServiceError):
                raise
            raise AnthropicServiceError(
                f"Anthropic API call failed: {str(e)}"
            ) from e

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
