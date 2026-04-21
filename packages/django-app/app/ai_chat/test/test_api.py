import uuid
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from ai_chat.models import (
    AIModel,
    ChatSession,
    UserAISettings,
    UserProviderConfig,
)
from ai_chat.services.base_ai_service import AIServiceError, AIServiceResult
from ai_chat.test.helpers import (
    AnthropicProviderFactory,
    ChatMessageFactory,
    ChatSessionFactory,
    OpenAIProviderFactory,
    UserAISettingsFactory,
    UserProviderConfigFactory,
)
from core.test.helpers import UserFactory


class AIChatAPITestCase(TestCase):
    """Test AI Chat API endpoints with mocked AI services"""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="test@example.com")
        cls.user.set_password("testpass123")
        cls.user.save()

        # Create AI providers
        cls.openai_provider = OpenAIProviderFactory()
        cls.anthropic_provider = AnthropicProviderFactory()

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

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

        # Create Anthropic models for testing
        self.claude_sonnet_model = AIModel.objects.create(
            name="claude-3-sonnet",
            provider=self.anthropic_provider,
            display_name="Claude 3 Sonnet",
            description="Test Claude 3 Sonnet model",
            is_active=True,
        )
        self.claude_haiku_model = AIModel.objects.create(
            name="claude-3-haiku",
            provider=self.anthropic_provider,
            display_name="Claude 3 Haiku",
            description="Test Claude 3 Haiku model",
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

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    def test_send_message_success(self, mock_create_service):
        """Test successful message sending through API"""
        # Mock AI service response
        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Hello! How can I help you today?"
        )
        mock_create_service.return_value = mock_service

        data = {"message": "Hello, AI!", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["response"], "Hello! How can I help you today?"
        )
        self.assertIn("session_id", response.data["data"])

        # Verify session and messages were created
        self.assertTrue(ChatSession.objects.filter(user=self.user).exists())
        session = ChatSession.objects.get(user=self.user)
        self.assertEqual(session.messages.count(), 2)  # User message + AI response

        # Verify mock was called correctly
        mock_create_service.assert_called_once_with(
            provider_name="openai",  # Determined from model name
            api_key="test-api-key-12345",
            model="gpt-4",
        )
        mock_service.send_message.assert_called_once()

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    def test_send_message_with_context_blocks(self, mock_create_service):
        """Test sending message with context blocks"""
        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Based on your notes, here's my advice..."
        )
        mock_create_service.return_value = mock_service

        data = {
            "message": "What should I do about this?",
            "model": "gpt-4",
            "context_blocks": [
                {"content": "Buy groceries", "block_type": "todo"},
                {"content": "Call dentist", "block_type": "done"},
                {"content": "Regular note", "block_type": "bullet"},
            ],
        }
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verify the user message includes formatted context
        session = ChatSession.objects.get(user=self.user)
        user_message = session.messages.filter(role="user").first()
        self.assertIn("**Context from my notes:**", user_message.content)
        self.assertIn("☐ Buy groceries", user_message.content)
        self.assertIn("☑ Call dentist", user_message.content)
        self.assertIn("• Regular note", user_message.content)
        self.assertIn("**My question:**", user_message.content)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    def test_send_message_with_existing_session(self, mock_create_service):
        """Test sending message to existing session"""
        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(
            content="Continuing our conversation..."
        )
        mock_create_service.return_value = mock_service

        # Create existing session with messages
        session = ChatSessionFactory(user=self.user)
        ChatMessageFactory(session=session, role="user", content="Previous message")
        ChatMessageFactory(
            session=session, role="assistant", content="Previous response"
        )

        data = {
            "message": "Follow-up question",
            "model": "gpt-4",
            "session_id": str(session.uuid),
        }
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["session_id"], str(session.uuid))

        # Verify messages were added to existing session
        session.refresh_from_db()
        self.assertEqual(session.messages.count(), 4)  # 2 existing + 2 new

    def test_send_message_empty_message(self):
        """Test sending empty message returns error"""
        data = {"message": "", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("Message cannot be empty", response.data["error"])

    def test_send_message_no_settings(self):
        """Test sending message without API key for the model's provider"""
        # Delete both user settings and provider config
        UserAISettings.objects.filter(user=self.user).delete()
        UserProviderConfig.objects.filter(user=self.user).delete()

        data = {"message": "Hello", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("No API key configured for OpenAI", response.data["error"])

    def test_send_message_no_api_key(self):
        """Test sending message without API key configured"""
        # Delete provider config (which contains API key)
        UserProviderConfig.objects.filter(user=self.user).delete()

        data = {"message": "Hello", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("No API key configured for OpenAI", response.data["error"])

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    def test_send_message_ai_service_error(self, mock_create_service):
        """Test handling AI service errors"""
        mock_create_service.side_effect = AIServiceError("API rate limit exceeded")

        data = {"message": "Hello", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("AI service error", response.data["error"])
        self.assertEqual(response.data["error_type"], "configuration_error")

    def test_send_message_authentication_required(self):
        """Test API authentication is required"""
        self.client.credentials()  # Remove authentication

        data = {"message": "Hello", "model": "gpt-4"}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_chat_sessions_list(self):
        """Test listing chat sessions"""
        # Create multiple sessions with messages
        session1 = ChatSessionFactory(user=self.user, title="First Chat")
        session2 = ChatSessionFactory(user=self.user, title="Second Chat")

        ChatMessageFactory(
            session=session1, role="user", content="First message in session 1"
        )
        ChatMessageFactory(
            session=session1, role="assistant", content="Response to first"
        )
        ChatMessageFactory(
            session=session2, role="user", content="Message in session 2"
        )

        response = self.client.get("/api/ai-chat/sessions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        sessions_data = response.data["data"]
        self.assertEqual(len(sessions_data), 2)

        # Check session data structure
        session_data = sessions_data[0]
        self.assertIn("uuid", session_data)
        self.assertIn("title", session_data)
        self.assertIn("preview", session_data)
        self.assertIn("created_at", session_data)
        self.assertIn("modified_at", session_data)
        self.assertIn("message_count", session_data)

    def test_chat_sessions_user_isolation(self):
        """Test that users only see their own sessions"""
        # Create session for test user
        ChatSessionFactory(user=self.user, title="My Session")

        # Create session for different user
        other_user = UserFactory(email="other@example.com")
        ChatSessionFactory(user=other_user, title="Other User Session")

        response = self.client.get("/api/ai-chat/sessions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sessions_data = response.data["data"]

        # Should only see own session
        self.assertEqual(len(sessions_data), 1)
        self.assertEqual(sessions_data[0]["title"], "My Session")

    def test_chat_session_detail(self):
        """Test getting detailed chat session with messages"""
        session = ChatSessionFactory(user=self.user, title="Test Session")
        ChatMessageFactory(session=session, role="user", content="Hello")
        ChatMessageFactory(session=session, role="assistant", content="Hi there!")

        response = self.client.get(f"/api/ai-chat/sessions/{session.uuid}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        session_data = response.data["data"]
        self.assertEqual(session_data["uuid"], str(session.uuid))
        self.assertEqual(session_data["title"], "Test Session")
        self.assertEqual(len(session_data["messages"]), 2)

        # Check message structure
        message = session_data["messages"][0]
        self.assertIn("role", message)
        self.assertIn("content", message)
        self.assertIn("created_at", message)

    def test_chat_session_detail_not_found(self):
        """Test getting non-existent session returns 404"""
        # Use a valid UUID format but non-existent session

        fake_uuid = str(uuid.uuid4())
        response = self.client.get(f"/api/ai-chat/sessions/{fake_uuid}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertIn("Chat session not found", response.data["error"])

    def test_chat_session_detail_other_user(self):
        """Test accessing other user's session returns 404"""
        other_user = UserFactory(email="other@example.com")
        session = ChatSessionFactory(user=other_user, title="Other User Session")

        response = self.client.get(f"/api/ai-chat/sessions/{session.uuid}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ai_settings_get(self):
        """Test getting AI settings"""
        response = self.client.get("/api/ai-chat/settings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        settings_data = response.data["data"]
        self.assertIn("providers", settings_data)
        self.assertIn("current_model", settings_data)
        self.assertIn("provider_configs", settings_data)

        self.assertEqual(settings_data["current_model"], "gpt-4")

    def test_update_ai_settings_success(self):
        """Test updating AI settings successfully"""
        data = {
            "provider": "Anthropic",
            "model": "claude-3-sonnet",
            "api_keys": {"Anthropic": "new-anthropic-key"},
            "provider_configs": {
                "Anthropic": {
                    "is_enabled": True,
                    "enabled_models": ["claude-3-sonnet", "claude-3-haiku"],
                }
            },
        }

        response = self.client.post(
            "/api/ai-chat/settings/update/", data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verify settings were updated
        user_settings = UserAISettings.objects.get(user=self.user)
        self.assertEqual(user_settings.preferred_model.name, "claude-3-sonnet")
        self.assertEqual(user_settings.preferred_model.provider.name, "Anthropic")

        # Verify provider config was created
        provider_config = UserProviderConfig.objects.get(
            user=self.user, provider=self.anthropic_provider
        )
        self.assertEqual(provider_config.api_key, "new-anthropic-key")
        self.assertTrue(provider_config.is_enabled)

        # Check enabled models (M2M relationship)
        enabled_model_names = list(
            provider_config.enabled_models.values_list("name", flat=True)
        )
        self.assertIn("claude-3-sonnet", enabled_model_names)
        self.assertIn("claude-3-haiku", enabled_model_names)

    def test_update_ai_settings_invalid_provider(self):
        """Test updating settings with invalid model"""
        data = {"provider": "NonExistentProvider", "model": "some-model"}

        response = self.client.post(
            "/api/ai-chat/settings/update/", data, format="json"
        )

        # With the new architecture, invalid models are logged but don't cause errors
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_api_endpoints_authentication_required(self):
        """Test all AI chat endpoints require authentication"""
        self.client.credentials()  # Remove authentication

        endpoints = [
            ("/api/ai-chat/send/", "post", {"message": "test", "model": "gpt-4"}),
            ("/api/ai-chat/sessions/", "get", None),
            ("/api/ai-chat/sessions/test-uuid/", "get", None),
            ("/api/ai-chat/settings/", "get", None),
            ("/api/ai-chat/settings/update/", "post", {"provider": "test"}),
        ]

        for url, method, data in endpoints:
            with self.subTest(url=url, method=method):
                if method == "post":
                    response = self.client.post(url, data or {}, format="json")
                else:
                    response = self.client.get(url)

                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    def test_send_message_invalid_session_id(self, mock_create_service):
        """Test sending message with invalid session ID creates new session"""
        mock_service = Mock()
        mock_service.send_message.return_value = AIServiceResult(content="Response")
        mock_create_service.return_value = mock_service

        # Use a properly formatted UUID that doesn't exist instead of "invalid-uuid"

        fake_uuid = str(uuid.uuid4())
        data = {"message": "Hello", "model": "gpt-4", "session_id": fake_uuid}
        response = self.client.post("/api/ai-chat/send/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Should create new session since non-existent UUID was provided
        self.assertTrue(ChatSession.objects.filter(user=self.user).exists())
