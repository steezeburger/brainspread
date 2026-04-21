import logging
from typing import Any, Dict, List, Optional

import anthropic

from .base_ai_service import AIServiceError, BaseAIService

logger = logging.getLogger(__name__)


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

    def send_message(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send messages to Anthropic API and return the response content.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            tools: Optional list of tools to make available to the model

        Returns:
            str: The assistant's response content

        Raises:
            AnthropicServiceError: If the API call fails
        """
        try:
            # Validate messages format using base class method
            self.validate_messages(messages)

            # Convert messages format for Anthropic API
            anthropic_messages = []
            system_message = None

            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    anthropic_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )

            # Prepare API call parameters
            kwargs = {
                "model": self.model,
                "max_tokens": 2000,
                "messages": anthropic_messages,
            }

            # Add system message if present
            if system_message:
                kwargs["system"] = system_message

            # Add tools if provided
            if tools:
                kwargs["tools"] = tools

            # Make the API call
            response = self.client.messages.create(**kwargs)

            # Extract the content from the response
            if response.content and len(response.content) > 0:
                # Handle different content block types
                content_parts = []
                for block in response.content:
                    # Handle text blocks
                    if hasattr(block, "text") and block.text:
                        content_parts.append(block.text)
                    # Handle tool use blocks (should be skipped)
                    elif hasattr(block, "type") and block.type == "tool_use":
                        continue
                    # Handle any other block types by trying to access text
                    elif hasattr(block, "__dict__"):
                        # Log the block structure for debugging
                        logger.debug(
                            f"Unknown block type: {type(block)}, attributes: {block.__dict__}"
                        )
                        # Try to extract text content if available
                        if hasattr(block, "text"):
                            content_parts.append(str(block.text))

                if content_parts:
                    return "\n".join(content_parts)
                else:
                    # If no text content found, return a fallback message
                    logger.warning(
                        f"No text content found in Anthropic response with {len(response.content)} blocks"
                    )
                    return "I apologize, but I encountered an issue processing the response. Please try again."
            else:
                raise AnthropicServiceError("No content blocks in Anthropic response")

        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            if isinstance(e, AnthropicServiceError):
                raise
            else:
                raise AnthropicServiceError(
                    f"Anthropic API call failed: {str(e)}"
                ) from e

    def validate_api_key(self) -> bool:
        """
        Validate the Anthropic API key by making a test call.

        Returns:
            bool: True if API key is valid, False otherwise
        """
        try:
            # Make a minimal test call to validate the API key
            test_messages = [{"role": "user", "content": "Hi"}]
            response = self.client.messages.create(
                model=self.model, max_tokens=1, messages=test_messages
            )
            return response is not None
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            return False
