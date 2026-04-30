import base64
import logging
from typing import Any, Dict, Iterator, List, Optional

from openai import OpenAI
from openai.types.chat import ChatCompletion

from .base_ai_service import (
    AIServiceError,
    AIServiceResult,
    AIUsage,
    BaseAIService,
    ToolExecutor,
)

logger = logging.getLogger(__name__)


class OpenAIServiceError(AIServiceError):
    """Custom exception for OpenAI service errors"""

    pass


class OpenAIService(BaseAIService):
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        super().__init__(api_key, model)
        try:
            self.client = OpenAI(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise OpenAIServiceError(f"Failed to initialize OpenAI client: {e}") from e

    def send_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> AIServiceResult:
        try:
            self.validate_messages(messages)

            # OpenAI takes the system prompt as a message; prepend it if provided
            # and not already embedded. Keeping the system message stable across
            # requests lets OpenAI's automatic prompt caching (>1024 tokens) kick in.
            chat_messages = self._to_openai_messages(messages)
            if system and not any(m["role"] == "system" for m in chat_messages):
                chat_messages = [{"role": "system", "content": system}] + chat_messages

            if tools:
                return self._send_message_with_responses_api(chat_messages, tools)

            kwargs = {
                "model": self.model,
                "messages": chat_messages,
                "max_tokens": 2000,
                "temperature": 0.7,
            }
            response: ChatCompletion = self.client.chat.completions.create(**kwargs)

            if not response.choices:
                raise OpenAIServiceError("No choices in OpenAI response")
            content = response.choices[0].message.content
            if not content:
                raise OpenAIServiceError("No content in OpenAI response")

            return AIServiceResult(
                content=content,
                usage=self._extract_usage(getattr(response, "usage", None)),
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            if isinstance(e, OpenAIServiceError):
                raise
            raise OpenAIServiceError(f"OpenAI API call failed: {str(e)}") from e

    def stream_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> Iterator[Dict[str, Any]]:
        try:
            self.validate_messages(messages)

            chat_messages = self._to_openai_messages(messages)
            if system and not any(m["role"] == "system" for m in chat_messages):
                chat_messages = [{"role": "system", "content": system}] + chat_messages

            # The Responses API (used for native web search) does not yet share
            # the same streaming contract as Chat Completions, and custom tool
            # loops require multiple round-trips. Fall back to the buffered
            # stream in either case.
            if tools or tool_executor is not None:
                yield from super().stream_message(
                    messages, tools, system=system, tool_executor=tool_executor
                )
                return

            kwargs = {
                "model": self.model,
                "messages": chat_messages,
                "max_tokens": 2000,
                "temperature": 0.7,
                "stream": True,
                "stream_options": {"include_usage": True},
            }

            content_parts: List[str] = []
            usage = AIUsage()

            stream = self.client.chat.completions.create(**kwargs)
            for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = self._extract_usage(chunk_usage)

                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta else None
                if text:
                    content_parts.append(text)
                    yield {"type": "text", "delta": text}

            content = "".join(content_parts)
            yield {
                "type": "done",
                "content": content,
                "thinking": None,
                "usage": usage,
            }
        except Exception as e:
            logger.error(f"OpenAI streaming error: {str(e)}")
            if isinstance(e, OpenAIServiceError):
                raise
            raise OpenAIServiceError(f"OpenAI streaming call failed: {str(e)}") from e

    def validate_api_key(self) -> bool:
        try:
            test_messages = [{"role": "user", "content": "Hi"}]
            response = self.client.chat.completions.create(
                model=self.model, messages=test_messages, max_tokens=1
            )
            return response is not None
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            return False

    def _send_message_with_responses_api(
        self, messages: List[Dict[str, str]], tools: List[Dict[str, Any]]
    ) -> AIServiceResult:
        """Send message using OpenAI's Responses API for native web search."""
        try:
            user_messages = [msg for msg in messages if msg["role"] == "user"]
            if not user_messages:
                raise OpenAIServiceError("No user messages found for Responses API")

            input_text = user_messages[-1]["content"]

            response = self.client.responses.create(
                model=self.model, tools=tools, input=input_text
            )

            content: Optional[str] = None
            if getattr(response, "output_text", None):
                content = response.output_text
            elif getattr(response, "output", None):
                for item in response.output:
                    if getattr(item, "type", None) == "message":
                        for content_item in getattr(item, "content", []) or []:
                            text = getattr(content_item, "text", None)
                            if text:
                                content = text
                                break
                    if content:
                        break

            if not content:
                raise OpenAIServiceError(
                    "No text content found in Responses API response"
                )

            return AIServiceResult(
                content=content,
                usage=self._extract_usage(getattr(response, "usage", None)),
            )

        except AttributeError as e:
            if "'OpenAI' object has no attribute 'responses'" in str(e):
                logger.warning(
                    "OpenAI SDK version doesn't support Responses API, falling back to Chat Completions without web search"
                )
                return self._send_message_without_tools(messages)
            raise OpenAIServiceError(f"OpenAI Responses API error: {str(e)}") from e
        except Exception as e:
            logger.error(f"OpenAI Responses API error: {str(e)}")
            if any(
                keyword in str(e).lower()
                for keyword in ["responses", "not found", "unsupported"]
            ):
                logger.warning(
                    "Responses API not available, falling back to Chat Completions without web search"
                )
                return self._send_message_without_tools(messages)
            raise OpenAIServiceError(
                f"OpenAI Responses API call failed: {str(e)}"
            ) from e

    def _send_message_without_tools(
        self, messages: List[Dict[str, str]]
    ) -> AIServiceResult:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.7,
        }
        response: ChatCompletion = self.client.chat.completions.create(**kwargs)

        if not response.choices:
            raise OpenAIServiceError("No choices in OpenAI response")
        content = response.choices[0].message.content
        if not content:
            raise OpenAIServiceError("No content in OpenAI response")

        return AIServiceResult(
            content=content,
            usage=self._extract_usage(getattr(response, "usage", None)),
        )

    @staticmethod
    def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert our provider-agnostic message dicts into the wire format
        the Chat Completions API expects. When an entry has `images`, the
        `content` field becomes a list of content-part dicts with the
        image encoded as a base64 data URL; everything else passes through
        unchanged.
        """
        out: List[Dict[str, Any]] = []
        for msg in messages:
            images = msg.get("images") or []
            if not images:
                out.append({"role": msg["role"], "content": msg["content"]})
                continue
            parts: List[Dict[str, Any]] = []
            if msg.get("content"):
                parts.append({"type": "text", "text": msg["content"]})
            for img in images:
                data_b64 = base64.b64encode(img["data"]).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{data_b64}"
                        },
                    }
                )
            out.append({"role": msg["role"], "content": parts})
        return out

    @staticmethod
    def _extract_usage(usage_obj: Any) -> AIUsage:
        if usage_obj is None:
            return AIUsage()

        # Chat Completions uses prompt_tokens/completion_tokens;
        # Responses API uses input_tokens/output_tokens.
        input_tokens = (
            getattr(usage_obj, "input_tokens", None)
            if getattr(usage_obj, "input_tokens", None) is not None
            else getattr(usage_obj, "prompt_tokens", 0)
        ) or 0
        output_tokens = (
            getattr(usage_obj, "output_tokens", None)
            if getattr(usage_obj, "output_tokens", None) is not None
            else getattr(usage_obj, "completion_tokens", 0)
        ) or 0

        cached = 0
        details = getattr(usage_obj, "prompt_tokens_details", None) or getattr(
            usage_obj, "input_tokens_details", None
        )
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0

        return AIUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached,
        )
