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
from knowledge.commands.list_overdue_blocks_command import ListOverdueBlocksCommand
from knowledge.commands.list_scheduled_blocks_command import ListScheduledBlocksCommand
from knowledge.commands.search_pages_command import SearchPagesCommand
from knowledge.commands.tag_blocks_command import TagBlocksCommand, UntagBlocksCommand
from knowledge.commands.update_block_command import UpdateBlockCommand
from knowledge.forms import (
    CreateBlockForm,
    CreatePageForm,
    GetPageWithBlocksForm,
    ScheduleBlockForm,
    ToggleBlockTodoForm,
)
from knowledge.forms.list_overdue_blocks_form import ListOverdueBlocksForm
from knowledge.forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from knowledge.forms.search_notes_form import SearchNotesForm
from knowledge.forms.search_pages_form import SearchPagesForm
from knowledge.forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
from knowledge.forms.update_block_form import UpdateBlockForm
from knowledge.models import Block
from knowledge.repositories import BlockRepository, PageRepository

# --- helpers -----------------------------------------------------------


def _form_errors_to_str(form) -> str:
    """Flatten Django form errors into one human-readable string."""
    parts = []
    for field, errs in form.errors.items():
        for err in errs:
            parts.append(f"{field}: {err}")
    return "; ".join(parts) or "validation failed"


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


def _resolve_parent_block(user: User, page, parent_uuid: str | None) -> Block | None:
    """Resolve an optional parent block, ensuring it lives on ``page``."""
    if not parent_uuid:
        return None
    parent = BlockRepository.get_by_uuid(parent_uuid, user=user)
    if not parent:
        raise ToolError(f"parent block {parent_uuid} not found")
    if parent.page_id != page.id:
        raise ToolError("parent block belongs to a different page")
    return parent


def _resolve_tag_pages(user: User, tags: list[str]) -> list[str]:
    """Resolve a list of tag slugs into page UUIDs.

    Strict-by-default: every tag must already exist as a page (matched
    by slug). Auto-creating tag pages on tag operations is a typo
    magnet, so we surface "tag 'wrok' not found" instead.
    """
    if not isinstance(tags, list) or not tags:
        raise ToolError("tags must be a non-empty list of slugs")
    page_uuids: list[str] = []
    missing: list[str] = []
    for raw in tags:
        slug = str(raw or "").strip().lstrip("#")
        if not slug:
            raise ToolError("tags must not contain empty values")
        page = PageRepository.get_by_slug(slug, user=user)
        if page is None:
            missing.append(slug)
        else:
            page_uuids.append(str(page.uuid))
    if missing:
        raise ToolError(
            f"tag(s) not found: {', '.join(missing)} — create the page(s) first"
        )
    return page_uuids


# --- handlers ----------------------------------------------------------


def _create_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    content = (args.get("content") or "").strip()
    if not content:
        raise ToolError("content is required")
    page = _page_for_slug_or_today(ctx.user, args.get("page_slug"))
    parent = _resolve_parent_block(ctx.user, page, args.get("parent_block_uuid"))
    block_type = (args.get("block_type") or "bullet").strip() or "bullet"
    data: dict[str, Any] = {
        "user": ctx.user.id,
        "page": str(page.uuid),
        "content": content,
        "block_type": block_type,
    }
    if parent is not None:
        data["parent"] = str(parent.uuid)
    form = CreateBlockForm(data=data)
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


def _edit_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        raise ToolError("block_uuid is required")
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        raise ToolError(f"no block found with uuid {block_uuid}")

    payload: dict[str, Any] = {"user": ctx.user.id, "block": str(block.uuid)}
    touched = False
    if args.get("content") is not None:
        payload["content"] = args["content"]
        touched = True
    block_type = args.get("block_type")
    if block_type:
        payload["block_type"] = block_type
        touched = True
    if not touched:
        raise ToolError("pass content and/or block_type to update")

    # UpdateBlockCommand orphans the block to root when "parent" is
    # missing — preserve the existing parent so a content-only edit
    # doesn't restructure the tree.
    if block.parent_id is not None:
        payload["parent"] = str(block.parent.uuid)

    form = UpdateBlockForm(data=payload)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    updated = UpdateBlockCommand(form).execute()
    return {"block": updated.to_dict(include_page_context=True)}


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


def _list_overdue(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"user": ctx.user.id}
    if args.get("limit") is not None:
        data["limit"] = args["limit"]
    form = ListOverdueBlocksForm(data=data)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    return ListOverdueBlocksCommand(form).execute()


def _list_scheduled(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"user": ctx.user.id}
    if args.get("start_date"):
        data["start_date"] = args["start_date"]
    if args.get("end_date"):
        data["end_date"] = args["end_date"]
    if args.get("limit") is not None:
        data["limit"] = args["limit"]
    form = ListScheduledBlocksForm(data=data)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    return ListScheduledBlocksCommand(form).execute()


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


def _search_pages(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user": ctx.user.id,
        "query": args.get("query") or "",
    }
    if args.get("limit") is not None:
        payload["limit"] = args["limit"]
    form = SearchPagesForm(data=payload)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    result = SearchPagesCommand(form).execute()
    return {"pages": result["pages"], "total_count": result["total_count"]}


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


def _tag_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        raise ToolError("block_uuid is required")
    page_uuids = _resolve_tag_pages(ctx.user, args.get("tags") or [])
    form = TagBlocksForm(
        data={
            "user": ctx.user.id,
            "block_uuids": [block_uuid],
            "page_uuids": page_uuids,
        }
    )
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    result = TagBlocksCommand(form).execute()
    if result.get("missing_blocks"):
        raise ToolError(f"block not found: {result['missing_blocks'][0]}")
    return result


def _untag_block(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        raise ToolError("block_uuid is required")
    page_uuids = _resolve_tag_pages(ctx.user, args.get("tags") or [])
    form = UntagBlocksForm(
        data={
            "user": ctx.user.id,
            "block_uuids": [block_uuid],
            "page_uuids": page_uuids,
        }
    )
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    result = UntagBlocksCommand(form).execute()
    if result.get("missing_blocks"):
        raise ToolError(f"block not found: {result['missing_blocks'][0]}")
    return result


# --- registry ----------------------------------------------------------

REGISTRY = ToolRegistry(
    [
        Tool(
            name="create_block",
            description=(
                "Add a block (note / TODO / heading / etc.) to a page."
                " Defaults to a bullet on today's daily note; pass"
                " block_type and/or page_slug to target a different shape"
                " or page. Use for quick capture ('remind me to call the"
                " dentist' → block_type='todo'). Pass parent_block_uuid"
                " to nest under another block on the same page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The block text."},
                    "block_type": {
                        "type": "string",
                        "description": (
                            "One of bullet (default), todo, doing, done,"
                            " later, wontdo, heading, code."
                        ),
                    },
                    "page_slug": {
                        "type": "string",
                        "description": (
                            "Slug of the target page. Omit to append to"
                            " today's daily note."
                        ),
                    },
                    "parent_block_uuid": {
                        "type": "string",
                        "description": (
                            "Optional uuid of a parent block on the target"
                            " page to nest this block under."
                        ),
                    },
                },
                "required": ["content"],
            },
            handler=_create_block,
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
            name="edit_block",
            description=(
                "Update a block's content and/or block_type. Pass at least"
                " one of content / block_type. block_type accepts 'bullet',"
                " 'todo', 'doing', 'done', 'later', 'wontdo', 'heading',"
                " etc. Preserves the block's parent — use the UI to"
                " re-parent."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": "New content. Omit to leave unchanged.",
                    },
                    "block_type": {
                        "type": "string",
                        "description": "New block_type. Omit to leave unchanged.",
                    },
                },
                "required": ["block_uuid"],
            },
            handler=_edit_block,
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
            name="list_overdue",
            description=(
                "All overdue scheduled blocks across every page (todo /"
                " doing / later with scheduled_for before today). Broader"
                " than list_today_todos, which only includes today's daily"
                " page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "1-100; defaults to 25.",
                    },
                },
            },
            handler=_list_overdue,
        ),
        Tool(
            name="list_scheduled",
            description=(
                "Scheduled blocks within a date range (inclusive). Use for"
                " 'what's coming up this week?'. Dates are ISO YYYY-MM-DD;"
                " omit both for the full upcoming view."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive lower bound, YYYY-MM-DD.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive upper bound, YYYY-MM-DD.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "1-200; defaults to 50.",
                    },
                },
            },
            handler=_list_scheduled,
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
            name="search_pages",
            description=(
                "Search the user's pages by title or slug substring. Use to"
                " discover a page by name before targeting it with"
                " create_note / get_page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "1-20; defaults to 10.",
                    },
                },
                "required": ["query"],
            },
            handler=_search_pages,
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
        Tool(
            name="tag_block",
            description=(
                "Tag a block with one or more existing pages. Pass tag"
                " slugs (e.g. 'work', 'ideas') — the leading '#' is"
                " optional. Tags that don't exist yet must be created via"
                " create_page first; this tool will error rather than"
                " silently creating typos."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tag slugs to add.",
                    },
                },
                "required": ["block_uuid", "tags"],
            },
            handler=_tag_block,
        ),
        Tool(
            name="untag_block",
            description=(
                "Remove one or more tags from a block. Same slug format as"
                " tag_block."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tag slugs to remove.",
                    },
                },
                "required": ["block_uuid", "tags"],
            },
            handler=_untag_block,
        ),
    ]
)
