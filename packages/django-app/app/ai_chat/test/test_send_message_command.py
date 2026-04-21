from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from ai_chat.commands.send_message_command import (
    BRAINSPREAD_SYSTEM_PROMPT,
    SendMessageCommand,
    SendMessageCommandError,
)
from ai_chat.forms import SendMessageForm
from ai_chat.models import AIModel
from ai_chat.services.ai_service_factory import AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError, AIServiceResult, AIUsage
from ai_chat.test.helpers import (
    ChatSessionFactory,
    OpenAIProviderFactory,
    UserAISettingsFactory,
    UserProviderConfigFactory,
)
from core.test.helpers import UserFactory


class SendMessageCommandTestCase(TestCase):
    """Test SendMessageCommand with mocked AI services"""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="test@example.com")
        cls.openai_provider = OpenAIProviderFactory()

    def setUp(self):
        # Create AIModel entries for testing
        self.gpt4_model = AIModel.objects.create(
            name="gpt-4",
            provider=self.openai_provider,
            display_name="GPT-4",
            description="Test GPT-4 model",
            is_active=True,
        )
        self.gpt35_model = AIModel.objects.create(
            name="gpt-3.5-turbo",
            provider=self.openai_provider,
            display_name="GPT-3.5 Turbo",
            description="Test GPT-3.5 model",
            is_active=True,
        )

        # Create user AI settings with preferred model
        self.user_settings = UserAISettingsFactory(
            user=self.user, preferred_model=self.gpt4_model
        )

        # Create provider config with API key
        self.provider_config = UserProviderConfigFactory(
            user=self.user,
            provider=self.openai_provider,
            api_key="test-api-key-12345",
            enabled_models=[self.gpt4_model, self.gpt35_model],
        )

    def _create_form(
        self, message="Hello, AI!", model="gpt-4", session_id=None, context_blocks=None
    ):
        """Helper to create a form with default values"""
        form_data = {
            "user": self.user.id,
            "message": message,
            "model": model,
            "context_blocks": context_blocks or [],
        }
        if session_id:
            form_data["session_id"] = str(session_id)
        return SendMessageForm(form_data)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_session_repository.ChatSessionRepository.create_session"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.add_message"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_execute_success_new_session(
        self,
        mock_get_messages,
        mock_add_message,
        mock_create_session,
        mock_create_service,
    ):
        """Test successful command execution with new session"""
        # Setup mocks
        mock_session = Mock()
        mock_session.uuid = "test-session-uuid"
        mock_create_session.return_value = mock_session

        mock_message = Mock()
        mock_message.role = "user"
        mock_message.content = "Hello, AI!"
        mock_get_messages.return_value = [mock_message]

        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Hello! How can I help you?",
            usage=AIUsage(input_tokens=3, output_tokens=5),
        )
        mock_create_service.return_value = mock_service

        # Execute command
        form = self._create_form()
        command = SendMessageCommand(form)
        result = command.execute()

        # Verify result
        self.assertEqual(result["response"], "Hello! How can I help you?")
        self.assertEqual(result["session_id"], "test-session-uuid")

        # Verify mocks were called correctly
        mock_create_session.assert_called_once_with(self.user)
        self.assertEqual(mock_add_message.call_count, 2)  # User message + AI response
        mock_create_service.assert_called_once_with(
            provider_name="openai",  # Determined from model
            api_key="test-api-key-12345",
            model="gpt-4",
        )
        mock_service.send_message.assert_called_once_with(
            [{"role": "user", "content": "Hello, AI!"}],
            [{"type": "web_search_preview", "search_context_size": "medium"}],
            system=BRAINSPREAD_SYSTEM_PROMPT,
            tool_executor=None,
        )

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.add_message"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_execute_success_existing_session(
        self, mock_get_messages, mock_add_message, mock_create_service
    ):
        """Test successful command execution with existing session"""
        # Create existing session
        session = ChatSessionFactory(user=self.user)

        # Setup mocks - need to return 3 messages (2 previous + new user message)
        mock_messages = [
            Mock(role="user", content="Previous message"),
            Mock(role="assistant", content="Previous response"),
            Mock(role="user", content="Follow-up question"),
        ]
        mock_get_messages.return_value = mock_messages

        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Follow-up response"
        )
        mock_create_service.return_value = mock_service

        # Execute command
        form = self._create_form(message="Follow-up question", session_id=session.uuid)
        command = SendMessageCommand(form)
        result = command.execute()

        # Verify result
        self.assertEqual(result["response"], "Follow-up response")
        self.assertEqual(result["session_id"], str(session.uuid))

        # Verify conversation history was passed to AI service
        mock_service.send_message.assert_called_once()
        call_args = mock_service.send_message.call_args[0][0]
        self.assertEqual(len(call_args), 3)  # Previous 2 + new user message

    def test_execute_no_api_key_for_model_error(self):
        """Test command fails when no API key configured for the model's provider"""
        # Delete provider config (which contains API key)
        self.provider_config.delete()

        form = self._create_form(model="gpt-4")  # OpenAI model

        with self.assertRaises(ValidationError) as context:
            command = SendMessageCommand(form)
            command.execute()

        error_message = str(context.exception)
        self.assertIn("No API key configured for OpenAI", error_message)

    def test_execute_unknown_model_error(self):
        """Test command fails when model is not found in database"""
        form = self._create_form(model="unknown-model-xyz")

        with self.assertRaises(ValidationError) as context:
            command = SendMessageCommand(form)
            command.execute()

        error_message = str(context.exception)
        self.assertIn("Model", error_message)
        self.assertIn("unknown-model-xyz", error_message)
        self.assertIn("not available or not found", error_message)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_session_repository.ChatSessionRepository.create_session"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.add_message"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_execute_ai_service_error(
        self,
        mock_get_messages,
        mock_add_message,
        mock_create_session,
        mock_create_service,
    ):
        """Test command handles AI service errors gracefully"""
        # Create a real session for the mocks
        session = ChatSessionFactory(user=self.user)
        mock_create_session.return_value = session

        # Mock get_messages to return the user message
        mock_user_message = Mock()
        mock_user_message.role = "user"
        mock_user_message.content = "Hello"
        mock_get_messages.return_value = [mock_user_message]

        # Make AI service fail
        mock_create_service.side_effect = AIServiceError("API rate limit exceeded")

        form = self._create_form(message="Hello")
        command = SendMessageCommand(form)

        with self.assertRaises(SendMessageCommandError) as context:
            command.execute()

        self.assertIn("AI service error", str(context.exception))

        # Verify error message was added to session
        calls = mock_add_message.call_args_list
        last_call = calls[-1]
        self.assertEqual(last_call[0][0], session)
        self.assertEqual(last_call[0][1], "assistant")
        self.assertEqual(
            last_call[0][2],
            "Sorry, I'm experiencing technical difficulties: API rate limit exceeded",
        )
        self.assertEqual(last_call.kwargs["ai_model"], self.gpt4_model)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_session_repository.ChatSessionRepository.create_session"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.add_message"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_execute_service_factory_error(
        self,
        mock_get_messages,
        mock_add_message,
        mock_create_session,
        mock_create_service,
    ):
        """Test command handles service factory errors"""
        # Create a real session for the mocks
        session = ChatSessionFactory(user=self.user)
        mock_create_session.return_value = session

        # Mock get_messages to return the user message
        mock_user_message = Mock()
        mock_user_message.role = "user"
        mock_user_message.content = "Hello"
        mock_get_messages.return_value = [mock_user_message]

        # Make service factory fail
        mock_create_service.side_effect = AIServiceFactoryError("Unsupported provider")

        form = self._create_form(message="Hello")
        command = SendMessageCommand(form)

        with self.assertRaises(SendMessageCommandError) as context:
            command.execute()

        self.assertIn("AI service error", str(context.exception))

    def test_format_message_with_context_blocks(self):
        """Test message formatting with context blocks"""
        context_blocks = [
            {"content": "Buy groceries", "block_type": "todo"},
            {"content": "Call dentist", "block_type": "done"},
            {"content": "Regular note", "block_type": "bullet"},
            {"content": "Heading note", "block_type": "heading"},
        ]

        form = self._create_form(
            message="What should I do?", context_blocks=context_blocks
        )
        command = SendMessageCommand(form)

        formatted_message = command._format_message_with_context(
            "What should I do?", context_blocks
        )

        # Verify context formatting
        self.assertIn("**Context from my notes:**", formatted_message)
        self.assertIn("☐ Buy groceries", formatted_message)
        self.assertIn("☑ Call dentist", formatted_message)
        self.assertIn("• Regular note", formatted_message)
        self.assertIn("• Heading note", formatted_message)  # Default to bullet
        self.assertIn("**My question:**", formatted_message)
        self.assertIn("What should I do?", formatted_message)

    def test_format_message_no_context_blocks(self):
        """Test message formatting without context blocks"""
        form = self._create_form(message="Simple question")
        command = SendMessageCommand(form)

        formatted_message = command._format_message_with_context("Simple question", [])
        self.assertEqual(formatted_message, "Simple question")

    def test_format_message_empty_context_blocks(self):
        """Test message formatting with empty context blocks"""
        context_blocks = [
            {"content": "", "block_type": "todo"},
            {"content": "   ", "block_type": "bullet"},
        ]

        form = self._create_form(
            message="Question with empty context", context_blocks=context_blocks
        )
        command = SendMessageCommand(form)

        formatted_message = command._format_message_with_context(
            "Question with empty context", context_blocks
        )
        self.assertEqual(formatted_message, "Question with empty context")

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_session_repository.ChatSessionRepository.create_session"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.add_message"
    )
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_execute_with_context_blocks_integration(
        self,
        mock_get_messages,
        mock_add_message,
        mock_create_session,
        mock_create_service,
    ):
        """Test full execution with context blocks"""
        # Setup mocks
        mock_session = Mock()
        mock_session.uuid = "test-session-uuid"
        mock_create_session.return_value = mock_session

        # The formatted message will be captured by get_messages
        mock_message = Mock()
        mock_message.role = "user"
        mock_message.content = "**Context from my notes:**\n☐ Important task\n\n**My question:**\nWhat to do?"
        mock_get_messages.return_value = [mock_message]

        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Based on your notes, here's what I suggest..."
        )
        mock_create_service.return_value = mock_service

        # Execute command with context blocks
        context_blocks = [{"content": "Important task", "block_type": "todo"}]
        form = self._create_form(message="What to do?", context_blocks=context_blocks)
        command = SendMessageCommand(form)
        result = command.execute()

        # Verify result
        self.assertEqual(
            result["response"], "Based on your notes, here's what I suggest..."
        )

        # Verify the user message was formatted with context
        user_message_call = mock_add_message.call_args_list[0]
        formatted_content = user_message_call[0][2]  # Third argument is content
        self.assertIn("**Context from my notes:**", formatted_content)
        self.assertIn("☐ Important task", formatted_content)
