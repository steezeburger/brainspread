import json
import logging
from typing import TypedDict

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .commands import SendMessageCommand, StreamSendMessageCommand
from .commands.send_message_command import SendMessageCommandError
from .forms import SendMessageForm
from .models import (
    AIModel,
    AIProvider,
    ChatSession,
    UserAISettings,
    UserProviderConfig,
)
from .repositories.user_settings_repository import UserSettingsRepository

logger = logging.getLogger(__name__)


class SendMessageResponse(TypedDict):
    response: str


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_message(request):
    """
    Handle AI chat message sending.

    Expected request data:
    - message: The user's message (required)
    - model: The AI model to use for this request (required)
    - session_id: Optional session ID to continue conversation
    - context_blocks: Optional list of context blocks

    API key is automatically retrieved from user settings.
    """
    try:
        data = request.data.copy()
        data["user"] = request.user.id
        form = SendMessageForm(data)
        if not form.is_valid():
            # Extract first error message from form errors
            error_message = (
                str(list(form.errors.values())[0][0])
                if form.errors
                else "Invalid form data"
            )
            return Response(
                {
                    "success": False,
                    "error": error_message,
                    "error_type": "configuration_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = SendMessageCommand(form)
        result = command.execute()
        return Response({"success": True, "data": result})

    except SendMessageCommandError as e:
        logger.warning(f"Command error for user {request.user.id}: {str(e)}")
        return Response(
            {"success": False, "error": str(e), "error_type": "configuration_error"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error in send_message for user {request.user.id}: {str(e)}"
        )
        return Response(
            {
                "success": False,
                "error": "An unexpected error occurred. Please try again.",
                "error_type": "server_error",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _sse_event(payload: dict) -> bytes:
    """Encode a dict as a single `data:` SSE frame."""
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


class StreamSendMessageView(APIView):
    """SSE endpoint for streaming assistant responses."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data.copy()
        data["user"] = request.user.id
        form = SendMessageForm(data)
        if not form.is_valid():
            error_message = (
                str(list(form.errors.values())[0][0])
                if form.errors
                else "Invalid form data"
            )
            return Response(
                {
                    "success": False,
                    "error": error_message,
                    "error_type": "configuration_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = StreamSendMessageCommand(form)

        def event_stream():
            try:
                for event in command.execute():
                    yield _sse_event(event)
            except SendMessageCommandError as e:
                logger.warning(
                    f"Stream command error for user {request.user.id}: {str(e)}"
                )
                yield _sse_event({"type": "error", "error": str(e)})
            except Exception as e:
                logger.error(
                    f"Unexpected error in stream_send_message for user {request.user.id}: {str(e)}"
                )
                yield _sse_event(
                    {"type": "error", "error": "An unexpected error occurred."}
                )

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chat_sessions(request):
    """
    Get list of chat sessions for the current user.
    """
    try:
        sessions = ChatSession.objects.filter(user=request.user).order_by(
            "-modified_at"
        )

        # Get first message from each session for preview
        sessions_data = []
        for session in sessions:
            first_message = session.messages.filter(role="user").first()
            preview = (
                first_message.content[:100] + "..."
                if first_message and len(first_message.content) > 100
                else (first_message.content if first_message else "")
            )

            sessions_data.append(
                {
                    "uuid": str(session.uuid),
                    "title": session.title or preview or "New Chat",
                    "preview": preview,
                    "created_at": session.created_at.isoformat(),
                    "modified_at": session.modified_at.isoformat(),
                    "message_count": session.messages.count(),
                }
            )

        return Response({"success": True, "data": sessions_data})

    except Exception as e:
        logger.error(
            f"Error fetching chat sessions for user {request.user.id}: {str(e)}"
        )
        return Response(
            {"success": False, "error": "Failed to fetch chat sessions"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chat_session_detail(request, session_id):
    """
    Get detailed chat session with all messages.
    """
    try:
        session = ChatSession.objects.get(uuid=session_id, user=request.user)
        messages = session.messages.select_related("ai_model__provider").all()

        messages_data = [
            {
                "role": msg.role,
                "content": msg.content,
                "thinking": msg.thinking or None,
                "created_at": msg.created_at.isoformat(),
                "usage": {
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "cache_creation_input_tokens": msg.cache_creation_input_tokens,
                    "cache_read_input_tokens": msg.cache_read_input_tokens,
                },
                "ai_model": (
                    {
                        "name": msg.ai_model.name,
                        "display_name": msg.ai_model.display_name,
                        "provider": msg.ai_model.provider.name,
                    }
                    if msg.ai_model
                    else None
                ),
            }
            for msg in messages
        ]

        session_data = {
            "uuid": str(session.uuid),
            "title": session.title,
            "created_at": session.created_at.isoformat(),
            "modified_at": session.modified_at.isoformat(),
            "messages": messages_data,
        }

        return Response({"success": True, "data": session_data})

    except ChatSession.DoesNotExist:
        return Response(
            {"success": False, "error": "Chat session not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        logger.error(
            f"Error fetching chat session {session_id} for user {request.user.id}: {str(e)}"
        )
        return Response(
            {"success": False, "error": "Failed to fetch chat session"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_settings(request):
    """
    Get AI settings for the current user.
    """
    try:
        # Get available providers
        providers = AIProvider.objects.all()
        # Get available models from database grouped by provider
        providers_data = []
        for provider in providers:
            models = AIModel.objects.filter(
                provider=provider, is_active=True
            ).values_list("name", flat=True)
            providers_data.append(
                {
                    "id": provider.id,
                    "uuid": str(provider.uuid),
                    "name": provider.name,
                    "models": list(models),
                }
            )

        # Get user's current settings
        user_settings_repo = UserSettingsRepository()
        user_settings = user_settings_repo.get_user_settings(request.user)
        current_model = None

        if user_settings and user_settings.preferred_model:
            current_model = user_settings.preferred_model.name

        # Get user provider configurations
        provider_configs = UserProviderConfig.objects.filter(user=request.user)
        configs_data = {}

        for config in provider_configs:
            configs_data[config.provider.name] = {
                "is_enabled": config.is_enabled,
                "has_api_key": bool(config.api_key),
                "enabled_models": list(
                    config.enabled_models.values_list("name", flat=True)
                ),
            }

        response_data = {
            "providers": providers_data,
            "current_model": current_model,
            "provider_configs": configs_data,
        }

        return Response({"success": True, "data": response_data})

    except Exception as e:
        logger.error(f"Error fetching AI settings for user {request.user.id}: {str(e)}")
        return Response(
            {"success": False, "error": "Failed to fetch AI settings"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_ai_settings(request):
    """
    Update AI settings for the current user.
    """
    try:
        provider_name = request.data.get("provider")
        model = request.data.get("model")
        api_keys = request.data.get("api_keys", {})  # Dict of provider_name: api_key
        provider_configs = request.data.get(
            "provider_configs", {}
        )  # Dict of provider configs

        # Update user AI settings
        if model:
            # Get the AIModel object for the preferred model
            try:
                ai_model = AIModel.objects.get(name=model, is_active=True)
                user_settings, created = UserAISettings.objects.get_or_create(
                    user=request.user,
                    defaults={"preferred_model": ai_model},
                )

                if not created:
                    user_settings.preferred_model = ai_model
                    user_settings.save()
            except AIModel.DoesNotExist:
                logger.warning(
                    f"AI model '{model}' not found when updating user settings"
                )

        # Update provider configurations
        for provider_name, config_data in provider_configs.items():
            try:
                provider = AIProvider.objects.get(name__iexact=provider_name)
                provider_config, created = UserProviderConfig.objects.get_or_create(
                    user=request.user,
                    provider=provider,
                    defaults={
                        "is_enabled": config_data.get("is_enabled", True),
                    },
                )

                if not created:
                    provider_config.is_enabled = config_data.get(
                        "is_enabled", provider_config.is_enabled
                    )
                    provider_config.save()

                # Handle enabled_models M2M relationship
                enabled_model_names = config_data.get("enabled_models", [])
                ai_models = AIModel.objects.filter(
                    name__in=enabled_model_names, provider=provider, is_active=True
                )
                provider_config.enabled_models.set(ai_models)

            except AIProvider.DoesNotExist:
                logger.warning(
                    f"Provider '{provider_name}' not found when updating config"
                )
                continue

        # Update API keys
        for provider_name, api_key in api_keys.items():
            try:
                provider = AIProvider.objects.get(name__iexact=provider_name)
                provider_config, created = UserProviderConfig.objects.get_or_create(
                    user=request.user, provider=provider, defaults={"api_key": api_key}
                )

                if not created:
                    provider_config.api_key = api_key
                    provider_config.save()

            except AIProvider.DoesNotExist:
                logger.warning(
                    f"Provider '{provider_name}' not found when updating API key"
                )
                continue

        return Response(
            {"success": True, "data": {"message": "AI settings updated successfully"}}
        )

    except Exception as e:
        logger.error(f"Error updating AI settings for user {request.user.id}: {str(e)}")
        return Response(
            {"success": False, "error": "Failed to update AI settings"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
