"""Read-only notes tools exposed to the assistant.

These are custom (client-executed) tools: the model emits a tool_use block,
we run the Django query, and return the result as a tool_result. They let
the assistant pull specific pages/blocks on demand instead of requiring
all context upfront.

Only read operations are exposed intentionally — write operations need a
richer permission and confirmation flow before we let the model act.
"""

from typing import Any, Dict, List

# Anthropic expects: {name, description, input_schema: JSONSchema}.
# OpenAI's function-calling expects: {type: "function", function: {name, ...}}.
# We store the common shape here and adapt per provider at the call site.
NOTES_TOOLS: List[Dict[str, Any]] = [
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


NOTES_TOOL_NAMES = frozenset(tool["name"] for tool in NOTES_TOOLS)


def anthropic_notes_tools() -> List[Dict[str, Any]]:
    """Notes tools in Anthropic's tool schema."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }
        for tool in NOTES_TOOLS
    ]


def openai_notes_tools() -> List[Dict[str, Any]]:
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
        for tool in NOTES_TOOLS
    ]
