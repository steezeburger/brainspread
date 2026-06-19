"""MCP Streamable-HTTP JSON-RPC endpoint.

Speaks just enough of the MCP wire protocol to support tools-only
servers (no resources/prompts). One POST endpoint that dispatches
JSON-RPC requests to a small set of handlers.

Auth: standard DRF token auth. The MCP client sends
``Authorization: Token <brainspread-token>`` on every request; the
authenticated user is what each tool acts on. This is intentionally
*not* OAuth — the MCP spec recommends OAuth for public servers, but
this server is per-user and reuses the existing token an account
already has.

We always respond with ``application/json`` (no SSE) since every
tool here completes synchronously. Streaming can be added later if a
tool needs progress notifications.
"""

import json
import logging
from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .tools import TOOLS, ToolError

logger = logging.getLogger(__name__)

# MCP protocol versions this server speaks. We echo back whichever
# the client asks for if we support it; otherwise we pick the latest.
SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

SERVER_INFO = {"name": "brainspread", "version": "0.1.0"}
SERVER_CAPABILITIES = {"tools": {"listChanged": False}}

# JSON-RPC error codes (https://www.jsonrpc.org/specification#error_object).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _handle_initialize(_user, params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = (
        requested
        if requested in SUPPORTED_PROTOCOL_VERSIONS
        else LATEST_PROTOCOL_VERSION
    )
    return {
        "protocolVersion": version,
        "capabilities": SERVER_CAPABILITIES,
        "serverInfo": SERVER_INFO,
    }


def _handle_tools_list(_user, _params: dict[str, Any]) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in TOOLS.values()
        ]
    }


def _handle_tools_call(user, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not name or name not in TOOLS:
        # MCP spec: unknown tool name is a tool error, not a protocol
        # error — surface it as isError so the model can recover.
        return _tool_error_result(f"Unknown tool: {name!r}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _tool_error_result("'arguments' must be an object")
    try:
        data = TOOLS[name].handler(user, args)
    except ToolError as e:
        return _tool_error_result(str(e))
    except Exception as e:
        # Don't leak internals to the client, but log for debugging.
        logger.exception("MCP tool %s failed", name)
        return _tool_error_result(f"Tool {name} failed: {e.__class__.__name__}")
    return {
        "content": [{"type": "text", "text": json.dumps(data, default=str)}],
        "isError": False,
    }


def _tool_error_result(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# Methods → handler. Notifications (methods starting with ``notifications/``)
# are silently accepted and produce no response per JSON-RPC.
METHOD_HANDLERS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
    "ping": lambda _u, _p: {},
}


def _dispatch_single(user, message: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC message. Returns None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "Invalid JSON-RPC envelope",
        )
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, "'params' must be an object")

    is_notification = req_id is None
    if not method:
        return (
            None
            if is_notification
            else _error(req_id, INVALID_REQUEST, "Missing 'method'")
        )
    if method.startswith("notifications/"):
        return None

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return (
            None
            if is_notification
            else _error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        )
    try:
        result = handler(user, params)
    except Exception as e:
        logger.exception("MCP method %s failed", method)
        return _error(req_id, INTERNAL_ERROR, str(e))
    return None if is_notification else _result(req_id, result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mcp_endpoint(request):
    """The single Streamable-HTTP MCP endpoint."""
    body = request.data
    if isinstance(body, list):
        # Batch request — respond with an array of responses for the
        # non-notification messages, or 204 if everything was a notification.
        responses = [
            r
            for r in (_dispatch_single(request.user, m) for m in body)
            if r is not None
        ]
        if not responses:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(responses)

    if not isinstance(body, dict):
        return Response(
            _error(
                None, INVALID_REQUEST, "Request body must be a JSON object or array"
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = _dispatch_single(request.user, body)
    if response is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(response)
