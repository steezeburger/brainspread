"""Notes tools exposed to the assistant.

These are custom (client-executed) tools: the model emits a tool_use block,
we run the Django query, and return the result as a tool_result.

Tools are split into `NOTES_READ_TOOLS` (safe, always-on when the user grants
the notes-tools scope) and `NOTES_WRITE_TOOLS` (guarded — every call must be
approved by the user via the PendingToolApproval flow before execution).
"""

from typing import Any, Dict, List

# Anthropic expects: {name, description, input_schema: JSONSchema}.
# OpenAI's function-calling expects: {type: "function", function: {name, ...}}.
# We store the common shape here and adapt per provider at the call site.
NOTES_READ_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_notes",
        "description": (
            "Full-text search over the user's note blocks. Returns up to `limit`"
            " matching blocks with their page title, block content, and block uuid."
            " Use this when the user refers to notes whose exact location is unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for in block content (case-insensitive).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matching blocks to return (default 10, max 25).",
                    "minimum": 1,
                    "maximum": 25,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_page_by_title",
        "description": (
            "Fetch a single page by its title (case-insensitive, exact match)"
            " along with its root blocks. Prefer this when the user names a page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Page title to look up.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "get_block_by_id",
        "description": (
            "Fetch a single block by uuid and its direct children. Use after"
            " search_notes to expand a promising hit into more detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to fetch.",
                },
            },
            "required": ["block_uuid"],
        },
    },
]


NOTES_WRITE_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "create_page",
        "description": (
            "Create a new page for the user. Use this before create_block if"
            " the target page doesn't exist yet. Every call pauses for"
            " explicit user approval before execution. Returns the new"
            " page's uuid and slug — pass that uuid to create_block to seed"
            " body content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the new page.",
                },
                "page_type": {
                    "type": "string",
                    "description": (
                        "Optional page type. Allowed: page (default) or"
                        " template. Do not use 'daily' (auto-created per"
                        " date) or 'whiteboard' (requires a tldraw snapshot"
                        " this tool can't produce)."
                    ),
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_block",
        "description": (
            "Create a new block on a page. Use after confirming the target"
            " page via get_page_by_title or search_notes. Every call pauses"
            " for explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_uuid": {
                    "type": "string",
                    "description": "UUID of the target page.",
                },
                "content": {
                    "type": "string",
                    "description": "Block content (markdown).",
                },
                "block_type": {
                    "type": "string",
                    "description": (
                        "Block type. Defaults to 'bullet'. Allowed: bullet,"
                        " todo, doing, done, later, wontdo, heading, code."
                    ),
                },
                "parent_uuid": {
                    "type": "string",
                    "description": (
                        "Optional UUID of parent block; omit for a root-level"
                        " block on the page."
                    ),
                },
                "order": {
                    "type": "integer",
                    "description": ("Optional order within parent; defaults to end."),
                },
            },
            "required": ["page_uuid", "content"],
        },
    },
    {
        "name": "edit_block",
        "description": (
            "Update an existing block: change its content, type, parent"
            " (re-nest), or order. All fields except block_uuid are"
            " optional — supply only what you want to change. To move a"
            " block to the page root pass parent_uuid=null. Every call"
            " pauses for explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to edit.",
                },
                "content": {
                    "type": "string",
                    "description": "New block content.",
                },
                "block_type": {
                    "type": "string",
                    "description": (
                        "Optional new block type. Same allowed values as create_block."
                    ),
                },
                "parent_uuid": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional new parent block UUID. Pass null to make"
                        " the block a root-level block on its current page."
                        " Cannot create a cycle."
                    ),
                },
                "order": {
                    "type": "integer",
                    "description": "Optional new order within the parent.",
                },
            },
            "required": ["block_uuid"],
        },
    },
    {
        "name": "reorder_blocks",
        "description": (
            "Reorder several sibling blocks in one call. Pass a list of"
            " {block_uuid, order} pairs — every listed block must already"
            " exist and belong to the user. This does NOT change parents"
            " or pages; use edit_block for that. Every call pauses for"
            " explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "blocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "block_uuid": {"type": "string"},
                            "order": {"type": "integer"},
                        },
                        "required": ["block_uuid", "order"],
                    },
                    "description": "List of block_uuid + order pairs.",
                },
            },
            "required": ["blocks"],
        },
    },
    {
        "name": "move_blocks",
        "description": (
            "Move one or more blocks to a different page. Each block becomes"
            " a root-level block on the target page. Every call pauses for"
            " explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of blocks to move.",
                },
                "target_page_uuid": {
                    "type": "string",
                    "description": "UUID of the target page.",
                },
            },
            "required": ["block_uuids", "target_page_uuid"],
        },
    },
]

# Back-compat alias — the read-only set used to be called NOTES_TOOLS.
NOTES_TOOLS = NOTES_READ_TOOLS

NOTES_READ_TOOL_NAMES = frozenset(tool["name"] for tool in NOTES_READ_TOOLS)
NOTES_WRITE_TOOL_NAMES = frozenset(tool["name"] for tool in NOTES_WRITE_TOOLS)
NOTES_TOOL_NAMES = NOTES_READ_TOOL_NAMES | NOTES_WRITE_TOOL_NAMES


def _all_notes_tools(include_writes: bool) -> List[Dict[str, Any]]:
    return list(NOTES_READ_TOOLS) + (list(NOTES_WRITE_TOOLS) if include_writes else [])


def anthropic_notes_tools(include_writes: bool = False) -> List[Dict[str, Any]]:
    """Notes tools in Anthropic's tool schema."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }
        for tool in _all_notes_tools(include_writes)
    ]


def openai_notes_tools(include_writes: bool = False) -> List[Dict[str, Any]]:
    """Notes tools in OpenAI's function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in _all_notes_tools(include_writes)
    ]
