"""Serialize a ChatMessage for API/stream responses.

Lives here rather than on SendMessageCommand because callers outside
ai_chat.commands need it too (the stream_runner worker thread renders
a message dict for every poll response, and it can't import
ai_chat.commands.send_message_command directly without joining a
cycle: ai_chat.commands eagerly imports StreamSendMessageCommand,
which imports stream_runner). Keeping the serializer in the services
layer — which commands are already allowed to depend on, but not the
reverse — means the dependency only ever points one way.
"""

from typing import Any, Dict


def serialize_chat_message(message, ai_model) -> Dict[str, Any]:
    # getattr-with-default keeps this resilient to test mocks that
    # don't pre-configure attachments (which is a new field).
    attachments = getattr(message, "attachments", None)
    if not isinstance(attachments, list):
        attachments = []
    return {
        "uuid": str(message.uuid),
        "role": message.role,
        "content": message.content,
        "thinking": message.thinking or None,
        "created_at": message.created_at.isoformat(),
        "tool_events": list(message.tool_events or []),
        "attachments": list(attachments),
        # Default to "complete" so legacy callers that don't set the
        # field on a mock still serialize a meaningful status.
        "status": getattr(message, "status", "complete"),
        "usage": {
            "input_tokens": message.input_tokens,
            "output_tokens": message.output_tokens,
            "cache_creation_input_tokens": message.cache_creation_input_tokens,
            "cache_read_input_tokens": message.cache_read_input_tokens,
        },
        "ai_model": (
            {
                "name": ai_model.name,
                "display_name": ai_model.display_name,
                "provider": ai_model.provider.name,
            }
            if ai_model
            else None
        ),
    }
