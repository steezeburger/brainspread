from unittest.mock import Mock, patch

import pytest
from google.api_core import exceptions as google_exceptions

from ai_chat.services.base_ai_service import AIServiceResult
from ai_chat.services.google_service import GoogleService, GoogleServiceError


class TestGoogleService:
    def test_init(self):
        """Test GoogleService initialization"""
        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")
        assert service.api_key == "test-key"
        assert service.model == "gemini-1.5-pro"

    @patch("google.generativeai.GenerativeModel")
    def test_send_message_success(self, mock_model_class):
        """Test successful message sending returns AIServiceResult with usage"""
        mock_response = Mock()
        mock_response.text = "Hello! How can I help you?"
        mock_response.usage_metadata = Mock(
            prompt_token_count=10,
            candidates_token_count=20,
            cached_content_token_count=0,
        )

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        messages = [{"role": "user", "content": "Hello"}]

        result = service.send_message(messages)

        assert isinstance(result, AIServiceResult)
        assert result.content == "Hello! How can I help you?"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 20
        mock_model.generate_content.assert_called_once()

        call_args = mock_model.generate_content.call_args[0][0]
        assert "User: Hello" in call_args

    @patch("google.generativeai.GenerativeModel")
    def test_send_message_with_system_message(self, mock_model_class):
        """Test message sending with system message"""
        mock_response = Mock()
        mock_response.text = "Response"
        mock_response.usage_metadata = None

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]

        service.send_message(messages)

        call_args = mock_model.generate_content.call_args[0][0]
        assert "System: You are a helpful assistant" in call_args
        assert "User: Hello" in call_args

    @patch("google.generativeai.GenerativeModel")
    def test_send_message_injects_caller_system_prompt(self, mock_model_class):
        """Caller-provided system= should be injected if no system msg is embedded."""
        mock_response = Mock()
        mock_response.text = "Response"
        mock_response.usage_metadata = None

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")
        service.send_message(
            [{"role": "user", "content": "Hi"}], system="You are brainspread."
        )

        call_args = mock_model.generate_content.call_args[0][0]
        assert "System: You are brainspread." in call_args

    @patch("google.generativeai.GenerativeModel")
    def test_send_message_empty_response(self, mock_model_class):
        """Test handling of empty response"""
        mock_response = Mock()
        mock_response.text = None
        mock_response.usage_metadata = None

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(GoogleServiceError, match="Empty response from Google AI"):
            service.send_message(messages)

    @patch("google.generativeai.GenerativeModel")
    def test_send_message_api_error(self, mock_model_class):
        """Test handling of Google API errors"""
        mock_model = Mock()
        mock_model.generate_content.side_effect = google_exceptions.GoogleAPIError(
            "API Error"
        )
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(GoogleServiceError, match="Google AI API error"):
            service.send_message(messages)

    def test_send_message_invalid_messages(self):
        """Test validation of invalid messages"""
        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        # Missing content
        invalid_messages = [{"role": "user"}]

        with pytest.raises(GoogleServiceError, match="Invalid message format"):
            service.send_message(invalid_messages)

    @patch("google.generativeai.GenerativeModel")
    def test_validate_api_key_success(self, mock_model_class):
        """Test successful API key validation"""
        mock_response = Mock()
        mock_response.text = "Hello"

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        result = service.validate_api_key()
        assert result is True

    @patch("google.generativeai.GenerativeModel")
    def test_validate_api_key_failure(self, mock_model_class):
        """Test API key validation failure"""
        mock_model = Mock()
        mock_model.generate_content.side_effect = google_exceptions.GoogleAPIError(
            "Invalid API key"
        )
        mock_model_class.return_value = mock_model

        service = GoogleService(api_key="invalid-key", model="gemini-1.5-pro")

        result = service.validate_api_key()
        assert result is False

    def test_format_messages_for_google(self):
        """Test message formatting for Google AI"""
        service = GoogleService(api_key="test-key", model="gemini-1.5-pro")

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        result = service._format_messages_for_google(messages)

        expected = "System: You are helpful\n\nUser: Hello\n\nAssistant: Hi there!\n\nUser: How are you?"
        assert result == expected
