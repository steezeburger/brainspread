"""Shared, transport-agnostic tool primitive.

See ``core.tools.base`` for the ``Tool`` / ``ToolRegistry`` /
``ToolContext`` primitive and ``core.tools.renderers`` for the wire-format
renderers consumed by mcp_server and ai_chat.
"""

from .base import Tool, ToolContext, ToolError, ToolHandler, ToolRegistry
from .dates import parse_relative_date
from .renderers import to_anthropic, to_mcp, to_openai

__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolHandler",
    "ToolRegistry",
    "parse_relative_date",
    "to_anthropic",
    "to_mcp",
    "to_openai",
]
