import logging
from typing import Any, Dict, Iterator, List, Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from .base_ai_service import (
    AIServiceError,
    AIServiceResult,
    AIUsage,
    BaseAIService,
    ToolExecutor,
)

logger = logging.getLogger(__name__)


class GoogleServiceError(AIServiceError):
    """Google AI service specific error"""

    pass


class GoogleService(BaseAIService):
    """Google AI (Gemini) service implementation"""

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model)
        genai.configure(api_key=api_key)
        self.client = genai.GenerativeModel(model)

    def send_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> AIServiceResult:
        try:
            self.validate_messages(messages)

            # Prepend the caller-supplied system prompt if one isn't already present.
            working_messages = list(messages)
            if system and not any(m["role"] == "system" for m in working_messages):
                working_messages = [
                    {"role": "system", "content": system}
                ] + working_messages

            tool_config = None
            if tools:
                tool_config = self._convert_tools_to_google_format(tools)

            formatted_messages = self._build_google_payload(working_messages)

            if tool_config:
                try:
                    response = self.client.generate_content(
                        formatted_messages, tools=tool_config
                    )
                except google_exceptions.GoogleAPIError as e:
                    if (
                        "Search Grounding is not supported" in str(e)
                        or "not supported" in str(e).lower()
                    ):
                        logger.warning(
                            f"Google Search Grounding not supported, falling back to regular generation: {e}"
                        )
                        response = self.client.generate_content(formatted_messages)
                    else:
                        raise e
                except Exception as e:
                    logger.warning(
                        f"Google Search tool failed, falling back to regular generation: {e}"
                    )
                    response = self.client.generate_content(formatted_messages)
            else:
                response = self.client.generate_content(formatted_messages)

            if not response.text:
                raise GoogleServiceError("Empty response from Google AI")

            return AIServiceResult(
                content=response.text,
                usage=self._extract_usage(response),
            )

        except google_exceptions.GoogleAPIError as e:
            logger.error(f"Google AI API error: {e}")
            raise GoogleServiceError(f"Google AI API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in Google AI service: {e}")
            raise GoogleServiceError(f"Unexpected error: {e}")

    def stream_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> Iterator[Dict[str, Any]]:
        try:
            self.validate_messages(messages)

            working_messages = list(messages)
            if system and not any(m["role"] == "system" for m in working_messages):
                working_messages = [
                    {"role": "system", "content": system}
                ] + working_messages

            # Streaming with Google's Search Grounding is not consistently
            # supported across SDK versions, and custom tool loops need
            # multiple round-trips, so fall back in either case.
            if tools or tool_executor is not None:
                yield from super().stream_message(
                    messages, tools, system=system, tool_executor=tool_executor
                )
                return

            formatted_messages = self._build_google_payload(working_messages)

            content_parts: List[str] = []
            last_chunk: Any = None

            stream = self.client.generate_content(formatted_messages, stream=True)
            for chunk in stream:
                last_chunk = chunk
                text = getattr(chunk, "text", None)
                if text:
                    content_parts.append(text)
                    yield {"type": "text", "delta": text}

            usage = (
                self._extract_usage(last_chunk) if last_chunk is not None else AIUsage()
            )
            yield {
                "type": "done",
                "content": "".join(content_parts),
                "thinking": None,
                "usage": usage,
            }
        except google_exceptions.GoogleAPIError as e:
            logger.error(f"Google streaming error: {e}")
            raise GoogleServiceError(f"Google AI streaming error: {e}")
        except Exception as e:
            logger.error(f"Google streaming error: {e}")
            if isinstance(e, GoogleServiceError):
                raise
            raise GoogleServiceError(f"Google streaming call failed: {e}")

    def validate_api_key(self) -> bool:
        try:
            test_model = genai.GenerativeModel("gemini-1.5-flash")
            response = test_model.generate_content("Hi")
            return response.text is not None
        except google_exceptions.GoogleAPIError:
            return False
        except Exception:
            return False

    def _format_messages_for_google(self, messages: List[Dict[str, Any]]) -> str:
        formatted_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                formatted_parts.append(f"System: {content}")
            elif role == "user":
                formatted_parts.append(f"User: {content}")
            elif role == "assistant":
                formatted_parts.append(f"Assistant: {content}")
        return "\n\n".join(formatted_parts)

    def _build_google_payload(self, messages: List[Dict[str, Any]]) -> Any:
        """
        Build the input for `generate_content`. With no images this stays
        the existing single-string transcript so prompt caching and
        truncation behave identically. With at least one image, we
        instead emit a list of parts ([text, image_part, ...]) which is
        what the Google SDK expects for multimodal input. The transcript
        text is preserved as the first part so all the prior turns are
        still in scope for the model.
        """
        has_images = any(msg.get("images") for msg in messages)
        if not has_images:
            return self._format_messages_for_google(messages)

        parts: List[Any] = [self._format_messages_for_google(messages)]
        for msg in messages:
            for img in msg.get("images") or []:
                parts.append({"mime_type": img["mime_type"], "data": img["data"]})
        return parts

    def _convert_tools_to_google_format(
        self, tools: List[Dict[str, Any]]
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            google_tools = []
            for tool in tools:
                if "google_search" in tool:
                    try:
                        google_tools.append({"google_search_retrieval": {}})
                        logger.info(
                            "Google Search grounding tool added (dictionary format)"
                        )
                    except Exception as e:
                        logger.warning(f"Google Search grounding method 1 failed: {e}")
                        try:
                            google_tools.append({"google_search": {}})
                            logger.info(
                                "Google Search grounding tool added (alternative format)"
                            )
                        except Exception as e2:
                            logger.warning(
                                f"Google Search grounding method 2 failed: {e2}"
                            )
                            continue
                elif "url_context" in tool:
                    logger.info("URL context tool not implemented yet")
                    continue

            return google_tools if google_tools else None

        except Exception as e:
            logger.warning(f"Google tools conversion failed: {e}")
            return None

    @staticmethod
    def _extract_usage(response: Any) -> AIUsage:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return AIUsage()
        return AIUsage(
            input_tokens=getattr(metadata, "prompt_token_count", 0) or 0,
            output_tokens=getattr(metadata, "candidates_token_count", 0) or 0,
            cache_read_input_tokens=(
                getattr(metadata, "cached_content_token_count", 0) or 0
            ),
        )
