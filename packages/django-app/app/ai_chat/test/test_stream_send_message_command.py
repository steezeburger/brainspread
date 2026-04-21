from unittest.mock import Mock, patch

from django.test import TestCase

from ai_chat.commands.stream_send_message_command import StreamSendMessageCommand
from ai_chat.forms import SendMessageForm
from ai_chat.models import AIModel
from ai_chat.services.base_ai_service import AIUsage
from ai_chat.test.helpers import (
    OpenAIProviderFactory,
    UserProviderConfigFactory,
)
from core.test.helpers import UserFactory


class StreamSendMessageCommandTestCase(TestCase):
    """Test StreamSendMessageCommand with mocked streaming services."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="stream@example.com")
        cls.openai_provider = OpenAIProviderFactory()

    def setUp(self):
        self.model = AIModel.objects.create(
            name="gpt-4",
            provider=self.openai_provider,
            display_name="GPT-4",
            is_active=True,
        )
        UserProviderConfigFactory(
            user=self.user,
            provider=self.openai_provider,
            api_key="stream-api-key",
            enabled_models=[self.model],
        )

    def _create_form(self):
        return SendMessageForm(
            {
                "user": self.user.id,
                "message": "Hello",
                "model": "gpt-4",
                "context_blocks": [],
            }
        )

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_emits_session_text_and_done_events(
        self, mock_get_messages, mock_create_service
    ):
        mock_get_messages.return_value = [Mock(role="user", content="Hello")]

        def fake_stream(messages, tools, system=None):
            yield {"type": "text", "delta": "Hi "}
            yield {"type": "text", "delta": "there"}
            yield {
                "type": "done",
                "content": "Hi there",
                "thinking": None,
                "usage": AIUsage(input_tokens=2, output_tokens=3),
            }

        mock_service = Mock()
        mock_service.stream_message.side_effect = fake_stream
        mock_create_service.return_value = mock_service

        form = self._create_form()
        command = StreamSendMessageCommand(form)
        events = list(command.execute())

        types = [e["type"] for e in events]
        self.assertEqual(types[0], "session")
        self.assertIn("text", types)
        self.assertEqual(types[-1], "done")

        text_deltas = [e["delta"] for e in events if e["type"] == "text"]
        self.assertEqual("".join(text_deltas), "Hi there")

        done = events[-1]
        self.assertEqual(done["message"]["content"], "Hi there")
        self.assertEqual(done["message"]["usage"]["input_tokens"], 2)
        self.assertEqual(done["message"]["usage"]["output_tokens"], 3)
