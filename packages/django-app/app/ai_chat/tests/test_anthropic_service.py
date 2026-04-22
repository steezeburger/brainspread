from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_chat.services.anthropic_service import (
    AnthropicService,
    AnthropicServiceError,
)
from ai_chat.services.base_ai_service import AIServiceResult


def _build_response(
    *,
    text: str = "hi there",
    thinking: str = "",
    input_tokens: int = 5,
    output_tokens: int = 7,
    cache_creation: int = 0,
    cache_read: int = 0,
):
    blocks = []
    if thinking:
        blocks.append(SimpleNamespace(type="thinking", thinking=thinking))
    blocks.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(content=blocks, usage=usage)


class TestAnthropicServiceThinking:
    @patch("anthropic.Anthropic")
    def test_enables_thinking_on_supported_model(self, mock_anthropic_cls):
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response(
            text="answer", thinking="reasoning trace"
        )
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-opus-4-7")
        result = service.send_message(
            [{"role": "user", "content": "Hello"}],
            system="brainspread system prompt",
        )

        assert isinstance(result, AIServiceResult)
        assert result.content == "answer"
        assert result.thinking == "reasoning trace"
        assert result.usage.input_tokens == 5
        assert result.usage.output_tokens == 7

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
        assert kwargs["output_config"] == {"effort": "high"}
        # System prompt is rendered as a cacheable block
        assert kwargs["system"] == [
            {
                "type": "text",
                "text": "brainspread system prompt",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    @patch("anthropic.Anthropic")
    def test_skips_thinking_on_non_4x_model(self, mock_anthropic_cls):
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response()
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-3-5-sonnet-legacy")
        service.send_message([{"role": "user", "content": "Hi"}])

        kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in kwargs

    @patch("anthropic.Anthropic")
    def test_extracts_cache_usage_counts(self, mock_anthropic_cls):
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response(
            cache_creation=100, cache_read=500
        )
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-haiku-4-5")
        result = service.send_message([{"role": "user", "content": "Hi"}])

        assert result.usage.cache_creation_input_tokens == 100
        assert result.usage.cache_read_input_tokens == 500

    @patch("anthropic.Anthropic")
    def test_haiku_gets_thinking_but_no_effort(self, mock_anthropic_cls):
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response()
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-haiku-4-5")
        service.send_message([{"role": "user", "content": "Hi"}])

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
        # effort would 400 on Haiku — make sure we don't send it.
        assert "output_config" not in kwargs

    @patch("anthropic.Anthropic")
    def test_validates_message_format(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = Mock()
        service = AnthropicService(api_key="k", model="claude-opus-4-7")

        with pytest.raises(AnthropicServiceError):
            service.send_message([{"role": "user"}])
