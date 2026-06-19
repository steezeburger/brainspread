"""Shared tool primitive.

A ``Tool`` is a name + description + JSON schema + handler. A
``ToolRegistry`` holds a curated set of tools and dispatches calls.
``ToolContext`` carries the per-call state (the acting user, plus
optional request-scoped extras like the page the user has open) that
every handler receives.

This layer is transport-agnostic. The MCP endpoint and the in-app AI
chat each build their *own* registry of curated tools over this
primitive and render the tool list to their wire format via
``core.tools.renderers``. The business logic still lives in Commands;
a handler is just the thin glue that shapes args into a Form and shapes
the Command's result back out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

if TYPE_CHECKING:
    from core.models import User


class ToolError(Exception):
    """A tool-level (not transport-level) error.

    Handlers raise this for input the model can recover from. Callers
    decide how to surface it: the MCP endpoint turns it into an
    ``isError`` result; the AI chat turns it into ``{"error": ...}``.
    """


@dataclass(frozen=True)
class ToolContext:
    """Per-call context handed to every tool handler.

    ``user`` is the acting user. ``current_page_uuid`` is the page the
    user has open in the UI when relevant — the AI chat passes it through
    from the request; the MCP endpoint leaves it ``None``. Handlers that
    don't need an extra just ignore it.
    """

    user: "User"
    current_page_uuid: Optional[str] = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    """A single callable tool exposed to an LLM."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    # Write tools gate behind a per-call approval in the AI chat; reads
    # run inline. The MCP endpoint ignores this today. Defaults to a read
    # tool so callers opt into write semantics explicitly.
    is_write: bool = False


class ToolRegistry:
    """An ordered, name-indexed set of tools.

    Each consumer (mcp_server, ai_chat) owns its own registry instance
    with its own curated tools; the registry just provides lookup,
    filtering, and dispatch so neither has to hand-roll an if/elif ladder.
    """

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def tools(self, *, include_writes: bool = True) -> list[Tool]:
        """The registered tools, optionally excluding write tools."""
        return [
            tool for tool in self._tools.values() if include_writes or not tool.is_write
        ]

    def execute(self, name: str, ctx: ToolContext, args: dict[str, Any]) -> Any:
        """Dispatch ``name`` to its handler. Raises ``ToolError`` if unknown."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool: {name}")
        return tool.handler(ctx, args)
