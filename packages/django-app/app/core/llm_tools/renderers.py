"""Render a set of ``Tool`` objects to each provider / transport format.

One place that knows how to turn the shared tool primitive into the wire
shape each consumer needs:

- Anthropic Messages API: ``{name, description, input_schema}``
- OpenAI function-calling: ``{type: "function", function: {...}}``
- MCP ``tools/list``: ``{name, description, inputSchema}``
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import Tool


def to_anthropic(tools: Iterable[Tool]) -> list[dict[str, Any]]:
    """Anthropic tool schema."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def to_openai(tools: Iterable[Tool]) -> list[dict[str, Any]]:
    """OpenAI function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def to_mcp(tools: Iterable[Tool]) -> list[dict[str, Any]]:
    """MCP ``tools/list`` schema (note the camelCase ``inputSchema``)."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in tools
    ]
