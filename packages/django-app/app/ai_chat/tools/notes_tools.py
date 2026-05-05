"""Notes tools exposed to the assistant.

These are custom (client-executed) tools: the model emits a tool_use block,
we run the Django query, and return the result as a tool_result.

Tools are split into `NOTES_READ_TOOLS` (safe, always-on when the user grants
the notes-tools scope) and `NOTES_WRITE_TOOLS` (guarded — every call must be
approved by the user via the PendingToolApproval flow before execution).

Scheduling/movement/completion tools live alongside the notes tools so they
flow through the same PendingToolApproval gate; they wrap the existing
ScheduleBlockCommand / SetBlockTypeCommand / MoveBlockToDailyCommand. See
issue #82.
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
    {
        "name": "get_current_time",
        "description": (
            "Return the current date + time in the user's timezone. Call"
            " this before scheduling a block / reminder when the user says"
            " something time-relative ('in 5 minutes', 'this afternoon')"
            " and you don't already know the exact local time. Returns"
            " ISO-8601 'now', plus separate date / time / weekday / timezone"
            " fields for convenience."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_overdue_blocks",
        "description": (
            "List the user's overdue scheduled blocks: blocks whose"
            " scheduled_for is before today (in the user's timezone) and"
            " whose block_type is still todo / doing / later. Same predicate"
            " that drives the daily-page overdue section. Returns block"
            " uuid, content, page title, scheduled_for, block_type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 25, max 100).",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    },
    {
        "name": "list_pending_reminders",
        "description": (
            "List reminders that haven't fired yet, oldest first. Each row"
            " includes the reminder fire_at timestamp (UTC), channel, and"
            " the parent block's uuid + content + page title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 25, max 100).",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    },
    {
        "name": "get_daily_pages_in_range",
        "description": (
            "Fetch the user's daily pages between two dates (inclusive),"
            " each with its root blocks. Use this to write weekly / monthly"
            " reviews or summarize what happened across a span of days."
            " The range is capped at 60 days to keep the result small."
            " Dates accept ISO YYYY-MM-DD or 'today' / 'tomorrow' /"
            " 'yesterday' / '+Nd' / '-Nd'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": (
                        "Inclusive lower bound. ISO YYYY-MM-DD, or 'today',"
                        " 'tomorrow', 'yesterday', '+Nd' / '-Nd'."
                    ),
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "Inclusive upper bound. Same format as start_date."
                    ),
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_completion_stats",
        "description": (
            "Counts of the user's blocks by block_type over a date range,"
            " plus a per-day breakdown of completions. done / wontdo are"
            " counted by completed_at within the range; todo / doing /"
            " later are counted by created_at within the range. Useful for"
            " 'how productive was I this week?' style questions. Range is"
            " capped at 366 days. Dates accept ISO YYYY-MM-DD or relative"
            " tokens ('today' / 'yesterday' / '+Nd' / '-Nd')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": (
                        "Inclusive lower bound. ISO YYYY-MM-DD, or 'today',"
                        " 'tomorrow', 'yesterday', '+Nd' / '-Nd'."
                    ),
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "Inclusive upper bound. Same format as start_date."
                    ),
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_streaks",
        "description": (
            "Return the user's current and longest consecutive-day streak"
            " for an activity. 'journal' = at least one block authored on"
            " that date's daily page; 'completion' = at least one block"
            " transitioned to done / wontdo on that date. Days are computed"
            " in the user's timezone. Looks back up to 366 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": (
                        "Activity to measure. Either 'journal' or 'completion'."
                    ),
                    "enum": ["journal", "completion"],
                },
                "as_of": {
                    "type": "string",
                    "description": (
                        "Optional reference date for the current streak."
                        " ISO YYYY-MM-DD or relative ('today', '-1d', etc)."
                        " Defaults to today in the user's timezone."
                    ),
                },
            },
            "required": ["kind"],
        },
    },
    {
        "name": "find_stale_todos",
        "description": (
            "List the user's open TODO blocks that are older than"
            " `older_than_days` days and have no scheduled_for date set."
            " Useful for surfacing forgotten work that has slipped through"
            " the cracks. Returns block uuid, content preview, page title,"
            " and how many days old the block is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "older_than_days": {
                    "type": "integer",
                    "description": (
                        "Minimum age in days, measured from block created_at"
                        " in the user's timezone. Default 14, max 365."
                    ),
                    "minimum": 1,
                    "maximum": 365,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 50, max 200).",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
        },
    },
    {
        "name": "list_scheduled_blocks",
        "description": (
            "List blocks with a scheduled_for date in the given inclusive"
            " range. Defaults: start_date = today (user tz), end_date ="
            " start_date + 30 days. Useful for 'what's coming up this week'"
            " questions. Dates accept ISO YYYY-MM-DD or 'today' / 'tomorrow'"
            " / '+Nd' offsets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": (
                        "Inclusive lower bound. ISO YYYY-MM-DD, or 'today',"
                        " 'tomorrow', 'yesterday', '+Nd' / '-Nd'. Default:"
                        " today in the user's timezone."
                    ),
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "Inclusive upper bound. Same format as start_date."
                        " Default: start_date + 30 days."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 50, max 200).",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
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
    {
        "name": "schedule_block",
        "description": (
            "Set a block's due date (scheduled_for), optionally creating a"
            " reminder. The block surfaces on the daily page for that date"
            " and shows up in the overdue section after it passes. Re-"
            "calling on the same block replaces any pending reminder; sent"
            " reminders stay as history. Pass an absolute ISO date or one of"
            " 'today' / 'tomorrow' / 'yesterday' / '+Nd' / '-Nd'. Reminder"
            " time is HH:MM 24-hour in the user's timezone. Use"
            " clear_schedule to unschedule a block. Every call pauses for"
            " explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to schedule.",
                },
                "scheduled_for": {
                    "type": "string",
                    "description": (
                        "Due date. ISO YYYY-MM-DD, or 'today' / 'tomorrow'"
                        " / 'yesterday' / '+Nd' / '-Nd'."
                    ),
                },
                "reminder_date": {
                    "type": "string",
                    "description": (
                        "Optional date for the reminder ping. Same format as"
                        " scheduled_for. Defaults to scheduled_for (i.e."
                        " 'remind me the day of'). Only used if"
                        " reminder_time is also set."
                    ),
                },
                "reminder_time": {
                    "type": "string",
                    "description": (
                        "Optional HH:MM 24-hour wall-clock time in the"
                        " user's timezone, OR a relative offset from now:"
                        " '+Nm' / '+Nh' (e.g. '+3m', '+2h'). Required to"
                        " actually create a reminder; without it the block"
                        " is scheduled but no ping fires. Relative offsets"
                        " override reminder_date if the offset crosses"
                        " midnight."
                    ),
                },
            },
            "required": ["block_uuid", "scheduled_for"],
        },
    },
    {
        "name": "clear_schedule",
        "description": (
            "Remove a block's due date and delete its pending reminder."
            " Sent reminders stay as history. Every call pauses for"
            " explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to unschedule.",
                },
            },
            "required": ["block_uuid"],
        },
    },
    {
        "name": "set_block_type",
        "description": (
            "Change a block's type (todo / doing / done / later / wontdo /"
            " bullet / heading / quote / code). Maintains completed_at on"
            " transitions into / out of done|wontdo and swaps the leading"
            " content prefix (TODO -> DONE etc). Use this to mark a todo"
            " as done from chat. Every call pauses for explicit user"
            " approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to update.",
                },
                "block_type": {
                    "type": "string",
                    "description": (
                        "New type. Allowed: bullet, todo, doing, done,"
                        " later, wontdo, heading, quote, code, divider."
                    ),
                },
            },
            "required": ["block_uuid", "block_type"],
        },
    },
    {
        "name": "move_block_to_daily",
        "description": (
            "Move a block (and its descendants) to a daily page. Defaults to"
            " today's daily in the user's timezone — useful for 'move that"
            " to today' / 'shove this onto tomorrow's daily' intents. The"
            " daily page is auto-created if it doesn't exist. The block"
            " becomes a root-level block on the target. Every call pauses"
            " for explicit user approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_uuid": {
                    "type": "string",
                    "description": "UUID of the block to move.",
                },
                "target_date": {
                    "type": "string",
                    "description": (
                        "Optional target date. ISO YYYY-MM-DD or 'today' /"
                        " 'tomorrow' / 'yesterday' / '+Nd' / '-Nd'. Default:"
                        " today in the user's timezone."
                    ),
                },
            },
            "required": ["block_uuid"],
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
