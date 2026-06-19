"""MCP tool registry.

Each tool is a thin adapter over a Forms + Command pair, matching the
project convention that all business logic lives in Commands. Handlers
take a ``ToolContext`` (the authenticated user) plus the JSON args sent
by the MCP client and return JSON-serializable data; the view layer wraps
the return value in MCP's ``content`` envelope.

The tool list is curated for an LLM caller — small surface, obvious
names, descriptions that read as instructions to the model. This is a
deliberately different (smaller, friendlier) surface than the in-app AI
chat's tool set, but both build on the same ``core.llm_tools`` primitive.
Add new tools by appending to ``REGISTRY`` at the bottom.
"""

from typing import Any

from core.llm_tools import Tool, ToolContext, ToolError, ToolRegistry
from core.models import User
from knowledge.commands import (
    CreateBlockCommand,
    CreatePageCommand,
    GetPageWithBlocksCommand,
    ScheduleBlockCommand,
    SearchNotesCommand,
    ToggleBlockTodoCommand,
)
from knowledge.forms import (
    CreateBlockForm,
    CreatePageForm,
    GetPageWithBlocksForm,
    ScheduleBlockForm,
    ToggleBlockTodoForm,
)
from knowledge.forms.search_notes_form import SearchNotesForm

# --- helpers -----------------------------------------------------------


def _form_errors_to_str(form) -> str:
    """Flatten Django form errors into one human-readable string."""
    parts = []
    for field, errs in form.errors.items():
        for err in errs:
            parts.append(f"{field}: {err}")
    return "; ".join(parts) or "validation failed"


def _today_daily_page(user: User):
    """Resolve (or create) today's daily page for ``user``."""
    form = GetPageWithBlocksForm(data={"user": user.id})
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    page, _direct, _refs, _overdue, _embeds = GetPageWithBlocksCommand(form).execute()
    return page


def _page_for_slug_or_today(user: User, slug: str | None):
    """Resolve a page by slug, or today's daily page when slug is empty."""
    data: dict[str, Any] = {"user": user.id}
    if slug:
        data["slug"] = slug
    form = GetPageWithBlocksForm(data=data)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    page, _direct, _refs, _overdue, _embeds = GetPageWithBlocksCommand(form).execute()
    return page


# --- handlers ----------------------------------------------------------


def _create_todo(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    content = (args.get("content") or "").strip()
    if not content:
        raise ToolError("content is required")
    page = _today_daily_page(ctx.user)
    form = CreateBlockForm(
        data={
            "user": ctx.user.id,
            "page": str(page.uuid),
            "content": content,
            "block_type": "todo",
        }
    )
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    block = CreateBlockCommand(form).execute()
    return {"block": block.to_dict(), "page": page.to_dict()}


def _create_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    content = (args.get("content") or "").strip()
    if not content:
        raise ToolError("content is required")
    page = _page_for_slug_or_today(ctx.user, args.get("page_slug"))
    form = CreateBlockForm(
        data={
            "user": ctx.user.id,
            "page": str(page.uuid),
            "content": content,
            "block_type": "bullet",
        }
    )
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    block = CreateBlockCommand(form).execute()
    return {"block": block.to_dict(), "page": page.to_dict()}


def _create_page(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"user": ctx.user.id, "title": args.get("title") or ""}
    if args.get("slug"):
        payload["slug"] = args["slug"]
    if args.get("page_type"):
        payload["page_type"] = args["page_type"]
    form = CreatePageForm(data=payload)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    page = CreatePageCommand(form).execute()
    return page.to_dict()


def _list_today_todos(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    form = GetPageWithBlocksForm(data={"user": ctx.user.id})
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    page, direct, _refs, overdue, _embeds = GetPageWithBlocksCommand(form).execute()
    undone = [b.to_dict() for b in direct if b.block_type in {"todo", "doing", "later"}]
    return {
        "page": page.to_dict(),
        "undone_today": undone,
        "overdue": [b.to_dict(include_page_context=True) for b in overdue],
    }


def _get_page(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"user": ctx.user.id}
    if args.get("slug"):
        data["slug"] = args["slug"]
    if args.get("date"):
        data["date"] = args["date"]
    form = GetPageWithBlocksForm(data=data)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    page, direct, refs, overdue, _embeds = GetPageWithBlocksCommand(form).execute()
    return {
        "page": page.to_dict(),
        "direct_blocks": [b.to_dict_with_children() for b in direct],
        "referenced_blocks": [b.to_dict(include_page_context=True) for b in refs],
        "overdue_blocks": [b.to_dict(include_page_context=True) for b in overdue],
    }


def _search_notes(ctx: ToolContext, args: dict[str, Any]) -> Any:
    payload: dict[str, Any] = {"user": ctx.user.id, "query": args.get("query") or ""}
    if args.get("limit") is not None:
        payload["limit"] = args["limit"]
    form = SearchNotesForm(data=payload)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    return SearchNotesCommand(form).execute()


def _toggle_todo(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    form = ToggleBlockTodoForm(
        data={"user": ctx.user.id, "block": args.get("block_uuid") or ""}
    )
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    block = ToggleBlockTodoCommand(form).execute()
    return block.to_dict()


def _schedule_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user": ctx.user.id,
        "block": args.get("block_uuid") or "",
        # ScheduleBlockForm treats empty/absent as "clear".
        "scheduled_for": args.get("scheduled_for") or "",
    }
    if args.get("reminder_time"):
        payload["reminder_time"] = args["reminder_time"]
    if args.get("reminder_date"):
        payload["reminder_date"] = args["reminder_date"]
    form = ScheduleBlockForm(data=payload)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    block = ScheduleBlockCommand(form).execute()
    return block.to_dict()


# --- registry ----------------------------------------------------------

REGISTRY = ToolRegistry(
    [
        Tool(
            name="create_todo",
            description=(
                "Add a TODO to today's daily page. Use for quick capture: "
                "'remind me to call the dentist', 'todo: ship the MCP server'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The TODO text.",
                    }
                },
                "required": ["content"],
            },
            handler=_create_todo,
        ),
        Tool(
            name="create_note",
            description=(
                "Add a free-form note (bullet block) to a page. Defaults to "
                "today's daily note; pass page_slug to target a specific page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The note text."},
                    "page_slug": {
                        "type": "string",
                        "description": (
                            "Slug of the target page. Omit to append to today's "
                            "daily note."
                        ),
                    },
                },
                "required": ["content"],
            },
            handler=_create_note,
        ),
        Tool(
            name="create_page",
            description="Create a new page.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "slug": {
                        "type": "string",
                        "description": "Optional; auto-generated from title when omitted.",
                    },
                    "page_type": {
                        "type": "string",
                        "description": "Usually 'page' (default) or 'template'.",
                    },
                },
                "required": ["title"],
            },
            handler=_create_page,
        ),
        Tool(
            name="list_today_todos",
            description=(
                "List undone TODOs on today's daily page, plus any overdue "
                "scheduled blocks. Use to answer 'what's on my plate today?'."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=_list_today_todos,
        ),
        Tool(
            name="get_page",
            description=(
                "Get a page with its blocks. Pass slug for a regular page, "
                "date (YYYY-MM-DD) for a daily note, or neither for today."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "date": {
                        "type": "string",
                        "description": "YYYY-MM-DD; selects that day's daily note.",
                    },
                },
            },
            handler=_get_page,
        ),
        Tool(
            name="search_notes",
            description="Substring search over block content.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 25,
                        "description": "1-25; defaults to 10.",
                    },
                },
                "required": ["query"],
            },
            handler=_search_notes,
        ),
        Tool(
            name="toggle_todo",
            description=(
                "Cycle a TODO block's state (todo → doing → done → todo). "
                "Use a block uuid from search_notes or list_today_todos."
            ),
            input_schema={
                "type": "object",
                "properties": {"block_uuid": {"type": "string"}},
                "required": ["block_uuid"],
            },
            handler=_toggle_todo,
        ),
        Tool(
            name="schedule_block",
            description=(
                "Set a block's due date (and optional reminder). "
                "scheduled_for is YYYY-MM-DD; empty string clears the schedule."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "scheduled_for": {
                        "type": "string",
                        "description": "YYYY-MM-DD, or empty to clear.",
                    },
                    "reminder_time": {
                        "type": "string",
                        "description": "HH:MM in the user's local timezone.",
                    },
                    "reminder_date": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD; defaults to scheduled_for when omitted."
                        ),
                    },
                },
                "required": ["block_uuid", "scheduled_for"],
            },
            handler=_schedule_block,
        ),
    ]
)
