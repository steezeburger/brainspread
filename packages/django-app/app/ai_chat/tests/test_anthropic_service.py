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
    def test_haiku_uses_enabled_thinking_not_adaptive(self, mock_anthropic_cls):
        # Haiku 4.5 supports extended thinking but NOT adaptive — the API
        # returns a 400 ("adaptive thinking is not supported on this model")
        # if we send `type: "adaptive"`. It needs `type: "enabled"` with an
        # explicit budget smaller than max_tokens.
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response()
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-haiku-4-5")
        service.send_message([{"role": "user", "content": "Hi"}])

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}
        assert kwargs["thinking"]["budget_tokens"] < kwargs["max_tokens"]
        # effort would also 400 on Haiku — make sure we don't send it.
        assert "output_config" not in kwargs

    @patch("anthropic.Anthropic")
    def test_validates_message_format(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = Mock()
        service = AnthropicService(api_key="k", model="claude-opus-4-7")

        with pytest.raises(AnthropicServiceError):
            service.send_message([{"role": "user"}])


class TestAnthropicResponseFormat:
    @patch("anthropic.Anthropic")
    def test_passes_json_schema_via_output_config_format(self, mock_anthropic_cls):
        # Anthropic's structured-output knob lives at output_config.format —
        # when the caller asks for json_schema, the schema must arrive in
        # that nested shape, alongside any pre-existing effort knob.
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response(text='{"a":1}')
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-opus-4-7")
        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        service.send_message(
            [{"role": "user", "content": "go"}],
            response_format={
                "type": "json_schema",
                "name": "ignored_by_anthropic",
                "schema": schema,
            },
        )

        kwargs = mock_client.messages.create.call_args.kwargs
        # output_config keeps effort AND gains the json_schema format
        assert kwargs["output_config"]["effort"] == "high"
        assert kwargs["output_config"]["format"] == {
            "type": "json_schema",
            "schema": schema,
        }

    @patch("anthropic.Anthropic")
    def test_omits_format_when_no_response_format(self, mock_anthropic_cls):
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response()
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-opus-4-7")
        service.send_message([{"role": "user", "content": "hi"}])

        kwargs = mock_client.messages.create.call_args.kwargs
        # Effort still set, but no `format` key — keeps the request shape
        # identical to pre-feature behaviour.
        assert kwargs["output_config"] == {"effort": "high"}

    @patch("anthropic.Anthropic")
    def test_skips_output_config_on_unsupported_model_without_format(
        self, mock_anthropic_cls
    ):
        # Older models don't accept output_config.effort. With no
        # response_format requested either, the kwarg should be omitted
        # entirely so the API doesn't 400.
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response()
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-3-5-sonnet-legacy")
        service.send_message([{"role": "user", "content": "hi"}])

        kwargs = mock_client.messages.create.call_args.kwargs
        assert "output_config" not in kwargs

    @patch("anthropic.Anthropic")
    def test_format_only_when_model_lacks_effort(self, mock_anthropic_cls):
        # If the model doesn't support effort but the caller asked for
        # a json_schema, output_config should still go out — just
        # without the effort knob.
        mock_client = Mock()
        mock_client.messages.create.return_value = _build_response(text="{}")
        mock_anthropic_cls.return_value = mock_client

        service = AnthropicService(api_key="k", model="claude-haiku-4-5")
        schema = {"type": "object"}
        service.send_message(
            [{"role": "user", "content": "x"}],
            response_format={"type": "json_schema", "schema": schema},
        )

        kwargs = mock_client.messages.create.call_args.kwargs
        assert "effort" not in kwargs.get("output_config", {})
        assert kwargs["output_config"]["format"] == {
            "type": "json_schema",
            "schema": schema,
        }


class TestSerializeBlock:
    """`_serialize_block` must round-trip every block type Anthropic emits
    so the next messages.create call accepts the replayed assistant turn.
    """

    def test_text_block(self):
        block = SimpleNamespace(type="text", text="hello")
        assert AnthropicService._serialize_block(block) == {
            "type": "text",
            "text": "hello",
        }

    def test_thinking_block_includes_signature(self):
        block = SimpleNamespace(type="thinking", thinking="reason", signature="sig")
        assert AnthropicService._serialize_block(block) == {
            "type": "thinking",
            "thinking": "reason",
            "signature": "sig",
        }

    def test_tool_use_block_keeps_id(self):
        block = SimpleNamespace(
            type="tool_use", id="tu_1", name="search_notes", input={"query": "x"}
        )
        assert AnthropicService._serialize_block(block) == {
            "type": "tool_use",
            "id": "tu_1",
            "name": "search_notes",
            "input": {"query": "x"},
        }

    def test_server_tool_use_block_keeps_id(self):
        # Regression: native web_search tool blocks were falling through to
        # the generic fallback, dropping `id`/`name`/`input`. Anthropic
        # then 400'd the next round-trip with
        # "server_tool_use.id: Field required".
        block = SimpleNamespace(
            type="server_tool_use",
            id="srvtu_1",
            name="web_search",
            input={"query": "weather sf"},
        )
        assert AnthropicService._serialize_block(block) == {
            "type": "server_tool_use",
            "id": "srvtu_1",
            "name": "web_search",
            "input": {"query": "weather sf"},
        }

    def test_web_search_tool_result_block_includes_results(self):
        result_item = SimpleNamespace(
            type="web_search_result",
            url="https://example.com",
            title="Example",
            encrypted_content="enc",
            page_age="2 days",
        )
        block = SimpleNamespace(
            type="web_search_tool_result",
            tool_use_id="srvtu_1",
            content=[result_item],
        )
        serialized = AnthropicService._serialize_block(block)
        assert serialized["type"] == "web_search_tool_result"
        assert serialized["tool_use_id"] == "srvtu_1"
        assert serialized["content"] == [
            {
                "type": "web_search_result",
                "url": "https://example.com",
                "title": "Example",
                "encrypted_content": "enc",
                "page_age": "2 days",
            }
        ]

    def test_web_search_tool_result_error_content(self):
        err = SimpleNamespace(
            type="web_search_tool_result_error", error_code="too_many_requests"
        )
        block = SimpleNamespace(
            type="web_search_tool_result", tool_use_id="srvtu_1", content=err
        )
        serialized = AnthropicService._serialize_block(block)
        assert serialized["content"] == {
            "type": "web_search_tool_result_error",
            "error_code": "too_many_requests",
        }

    def test_redacted_thinking_block(self):
        block = SimpleNamespace(type="redacted_thinking", data="opaque")
        assert AnthropicService._serialize_block(block) == {
            "type": "redacted_thinking",
            "data": "opaque",
        }
