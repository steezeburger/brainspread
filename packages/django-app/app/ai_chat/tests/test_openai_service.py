from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_chat.services.base_ai_service import AIServiceResult
from ai_chat.services.openai_service import OpenAIService


def _build_chat_response(
    *,
    text: str = "hi",
    prompt_tokens: int = 42,
    completion_tokens: int = 13,
    cached_tokens: int = 0,
):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    details = SimpleNamespace(cached_tokens=cached_tokens)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=details,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


class TestOpenAIServiceUsage:
    @patch("ai_chat.services.openai_service.OpenAI")
    def test_extracts_usage_and_cached_tokens(self, mock_openai_cls):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _build_chat_response(
            cached_tokens=20
        )
        mock_openai_cls.return_value = mock_client

        service = OpenAIService(api_key="k", model="gpt-4o")
        result = service.send_message([{"role": "user", "content": "hi"}])

        assert isinstance(result, AIServiceResult)
        assert result.content == "hi"
        assert result.usage.input_tokens == 42
        assert result.usage.output_tokens == 13
        assert result.usage.cache_read_input_tokens == 20

    @patch("ai_chat.services.openai_service.OpenAI")
    def test_injects_caller_system_prompt(self, mock_openai_cls):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _build_chat_response()
        mock_openai_cls.return_value = mock_client

        service = OpenAIService(api_key="k", model="gpt-4o")
        service.send_message(
            [{"role": "user", "content": "hi"}], system="brainspread system"
        )

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["messages"][0] == {
            "role": "system",
            "content": "brainspread system",
        }

    @patch("ai_chat.services.openai_service.OpenAI")
    def test_does_not_duplicate_system_prompt(self, mock_openai_cls):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _build_chat_response()
        mock_openai_cls.return_value = mock_client

        service = OpenAIService(api_key="k", model="gpt-4o")
        service.send_message(
            [
                {"role": "system", "content": "embedded"},
                {"role": "user", "content": "hi"},
            ],
            system="outer system",
        )

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_messages = [m for m in kwargs["messages"] if m["role"] == "system"]
        assert len(system_messages) == 1
        assert system_messages[0]["content"] == "embedded"
