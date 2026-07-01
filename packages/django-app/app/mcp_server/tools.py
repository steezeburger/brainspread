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

from django.core.exceptions import ValidationError

from core.commands.get_current_time_command import GetCurrentTimeCommand
from core.forms import GetCurrentTimeForm
from core.llm_tools import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    parse_relative_date,
)
from core.models import User
from knowledge.commands import (
    CreateBlockCommand,
    CreatePageCommand,
    GetPageWithBlocksCommand,
    ReorderBlocksCommand,
    ScheduleBlockCommand,
    SearchNotesCommand,
    ToggleBlockTodoCommand,
)
from knowledge.commands.list_overdue_blocks_command import ListOverdueBlocksCommand
from knowledge.commands.list_scheduled_blocks_command import ListScheduledBlocksCommand
from knowledge.commands.move_block_to_daily_command import MoveBlockToDailyCommand
from knowledge.commands.search_pages_command import SearchPagesCommand
from knowledge.commands.set_block_completed_at_command import (
    SetBlockCompletedAtCommand,
)
from knowledge.commands.tag_blocks_command import TagBlocksCommand, UntagBlocksCommand
from knowledge.commands.update_block_command import UpdateBlockCommand
from knowledge.forms import (
    CreateBlockForm,
    CreatePageForm,
    GetPageWithBlocksForm,
    ReorderBlocksForm,
    ScheduleBlockForm,
    ToggleBlockTodoForm,
)
from knowledge.forms.list_overdue_blocks_form import ListOverdueBlocksForm
from knowledge.forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from knowledge.forms.move_block_to_daily_form import MoveBlockToDailyForm
from knowledge.forms.search_notes_form import SearchNotesForm
from knowledge.forms.search_pages_form import SearchPagesForm
from knowledge.forms.set_block_completed_at_form import SetBlockCompletedAtForm
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


def _date_arg(user: User, value: Any, *, field: str) -> str | None:
    """Resolve a date arg (ISO or relative token) into an ISO string.

    Returns None when the input is empty / missing so the caller can
    leave the corresponding form field unset. Raises ToolError with a
    field-tagged message on bad input.
    """
    try:
        parsed = parse_relative_date(value, user.today())
    except ValueError as e:
        raise ToolError(f"{field}: {e}") from e
    return parsed.isoformat() if parsed is not None else None


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
    order = args.get("order")
    if order is not None:
        try:
            payload["order"] = int(order)
        except (TypeError, ValueError) as e:
            raise ToolError("order must be an integer") from e
        touched = True
    completed_at = args.get("completed_at")
    if not touched and completed_at is None:
        raise ToolError(
            "pass content, block_type, order, and/or completed_at to update"
        )

    updated = block
    if touched:
        # UpdateBlockCommand orphans the block to root when "parent" is
        # missing — preserve the existing parent so a content-only edit
        # doesn't restructure the tree.
        if block.parent_id is not None:
            payload["parent"] = str(block.parent.uuid)

        form = UpdateBlockForm(data=payload)
        if not form.is_valid():
            raise ToolError(_form_errors_to_str(form))
        updated = UpdateBlockCommand(form).execute()

    # Override completion time last, so a combined "mark done + set time"
    # call lands on the caller's timestamp rather than "now". The form
    # rejects completed_at on non-terminal blocks.
    if completed_at is not None:
        ca_form = SetBlockCompletedAtForm(
            data={
                "user": ctx.user.id,
                "block": str(updated.uuid),
                "completed_at": completed_at,
            }
        )
        if not ca_form.is_valid():
            raise ToolError(_form_errors_to_str(ca_form))
        updated = SetBlockCompletedAtCommand(ca_form).execute()

    return {"block": updated.to_dict(include_page_context=True)}


def _reorder_blocks(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    items = args.get("blocks") or []
    if not isinstance(items, list) or not items:
        raise ToolError("blocks must be a non-empty list")

    payload_blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ToolError("each blocks entry must be an object")
        block_uuid = (item.get("block_uuid") or "").strip()
        if not block_uuid:
            raise ToolError("each entry needs block_uuid")
        if block_uuid in seen:
            raise ToolError(f"duplicate block_uuid {block_uuid}")
        seen.add(block_uuid)
        try:
            order = int(item.get("order"))
        except (TypeError, ValueError) as e:
            raise ToolError("each entry needs an integer order") from e
        payload_blocks.append({"uuid": block_uuid, "order": order})

    form = ReorderBlocksForm(data={"user": ctx.user.id, "blocks": payload_blocks})
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    try:
        ReorderBlocksCommand(form).execute()
    except ValidationError as e:
        raise ToolError("; ".join(e.messages)) from e

    return {"reordered": True, "count": len(payload_blocks)}


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
    start = _date_arg(ctx.user, args.get("start_date"), field="start_date")
    if start is not None:
        data["start_date"] = start
    end = _date_arg(ctx.user, args.get("end_date"), field="end_date")
    if end is not None:
        data["end_date"] = end
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
    parsed_date = _date_arg(ctx.user, args.get("date"), field="date")
    if parsed_date is not None:
        data["date"] = parsed_date
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


def _get_current_time(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    """Return now in the user's local timezone, plus a friendly breakdown."""
    form = GetCurrentTimeForm({"user": ctx.user.id})
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    return GetCurrentTimeCommand(form).execute()


def _move_block_to_daily(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        raise ToolError("block_uuid is required")
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        raise ToolError(f"no block found with uuid {block_uuid}")

    target_date = _date_arg(ctx.user, args.get("target_date"), field="target_date")
    source_page_uuid = str(block.page.uuid) if block.page else None

    data: dict[str, Any] = {"user": ctx.user.id, "block": str(block.uuid)}
    if target_date is not None:
        data["target_date"] = target_date

    form = MoveBlockToDailyForm(data=data)
    if not form.is_valid():
        raise ToolError(_form_errors_to_str(form))
    result = MoveBlockToDailyCommand(form).execute()

    affected = {result["target_page"]["uuid"]}
    if source_page_uuid:
        affected.add(source_page_uuid)
    return {
        "moved": result["moved"],
        "message": result["message"],
        "block": result["block"],
        "target_page": result["target_page"],
        "affected_page_uuids": sorted(affected),
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
    due_date = _date_arg(ctx.user, args.get("due_date"), field="due_date")
    payload: dict[str, Any] = {
        "user": ctx.user.id,
        "block": args.get("block_uuid") or "",
        # ScheduleBlockForm treats empty/absent as "clear".
        "due_date": due_date or "",
    }
    if args.get("due_time"):
        payload["due_time"] = args["due_time"]
    if args.get("reminder_time"):
        payload["reminder_time"] = args["reminder_time"]
    reminder_date = _date_arg(
        ctx.user, args.get("reminder_date"), field="reminder_date"
    )
    if reminder_date is not None:
        payload["reminder_date"] = reminder_date
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
                "Update a block's content, block_type, order, and/or"
                " completion time. Pass at least one of content / block_type"
                " / order / completed_at. block_type accepts 'bullet',"
                " 'todo', 'doing', 'done', 'later', 'wontdo', 'heading', etc."
                " order moves the block among its siblings (lower sorts"
                " first); to resequence several siblings at once prefer"
                " reorder_blocks. completed_at corrects when a done / wontdo"
                " block was actually completed. Preserves the block's"
                " parent — use the UI to re-parent."
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
                    "order": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "New sort position among siblings (0-based, lower"
                            " sorts first). Omit to leave unchanged."
                        ),
                    },
                    "completed_at": {
                        "type": "string",
                        "description": (
                            "ISO-8601 datetime to record as the completion"
                            " time. Only valid for done / wontdo blocks."
                            " Include a timezone offset; a naive value is"
                            " read in the user's timezone. Omit to leave"
                            " unchanged."
                        ),
                    },
                },
                "required": ["block_uuid"],
            },
            handler=_edit_block,
        ),
        Tool(
            name="reorder_blocks",
            description=(
                "Resequence a set of sibling blocks in one call. Pass the"
                " full ordered list of blocks (each with its new 0-based"
                " order); the lowest order sorts first. Use this to move a"
                " block up/down or sort a list — it only changes ordering,"
                " not parents or pages. All blocks must belong to the"
                " caller. Read the current orders first (e.g. via get_page)"
                " so the new sequence is contiguous and gap-free."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "blocks": {
                        "type": "array",
                        "description": (
                            "Ordered list of blocks to resequence. Each item"
                            " is {block_uuid, order}."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "block_uuid": {"type": "string"},
                                "order": {"type": "integer", "minimum": 0},
                            },
                            "required": ["block_uuid", "order"],
                        },
                        "minItems": 1,
                    },
                },
                "required": ["blocks"],
            },
            handler=_reorder_blocks,
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
                " doing / later with due_at before today). Broader"
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
                " 'what's coming up this week?'. Dates accept ISO"
                " YYYY-MM-DD or relative tokens ('today', 'tomorrow',"
                " 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw'). Omit both"
                " bounds for the full upcoming view."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": (
                            "Inclusive lower bound. ISO YYYY-MM-DD or a"
                            " relative token ('today', '+7d', etc.)."
                        ),
                    },
                    "end_date": {
                        "type": "string",
                        "description": (
                            "Inclusive upper bound. Same format as start_date."
                        ),
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
                "Get a page with its blocks. Pass slug for a regular page,"
                " date for a daily note, or neither for today. date accepts"
                " ISO YYYY-MM-DD or relative tokens ('today', 'tomorrow',"
                " 'yesterday', '+Nd', '-Nd')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "date": {
                        "type": "string",
                        "description": (
                            "ISO YYYY-MM-DD or relative token; selects that"
                            " day's daily note."
                        ),
                    },
                },
            },
            handler=_get_page,
        ),
        Tool(
            name="get_current_time",
            description=(
                "Return the current date + time in the user's timezone."
                " Call this before scheduling far-out dates when the user"
                " says something time-relative that the simple relative"
                " tokens can't express ('6 months from now', 'next"
                " Tuesday', 'my birthday next year') so the model can"
                " compute the absolute ISO date itself. For simple"
                " offsets like 'tomorrow' or '+7d', just pass the token"
                " straight to the date arg instead."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=_get_current_time,
        ),
        Tool(
            name="move_block_to_daily",
            description=(
                "Move a block from its current page to a daily note,"
                " creating that daily page if it doesn't exist yet."
                " Distinct from schedule_block: scheduling sets a due"
                " date but leaves the block where it is; this physically"
                " relocates it so it shows up on the daily. Use for"
                " 'move this to tomorrow's daily', 'pull all overdue"
                " todos to today'. target_date accepts ISO YYYY-MM-DD or"
                " a relative token; defaults to today."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "target_date": {
                        "type": "string",
                        "description": (
                            "ISO YYYY-MM-DD or relative token ('today',"
                            " 'tomorrow', '+1d'). Defaults to today."
                        ),
                    },
                },
                "required": ["block_uuid"],
            },
            handler=_move_block_to_daily,
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
                "Set a block's due date (and optional reminder). Dates"
                " accept ISO YYYY-MM-DD or relative tokens ('today',"
                " 'tomorrow', 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw')."
                " Due is all-day unless due_time is given. Empty due_date"
                " clears the due date."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "block_uuid": {"type": "string"},
                    "due_date": {
                        "type": "string",
                        "description": (
                            "ISO YYYY-MM-DD or relative token, or empty to" " clear."
                        ),
                    },
                    "due_time": {
                        "type": "string",
                        "description": (
                            "Optional HH:MM (user's local tz) for a timed"
                            " due; omit for an all-day due."
                        ),
                    },
                    "reminder_time": {
                        "type": "string",
                        "description": "HH:MM in the user's local timezone.",
                    },
                    "reminder_date": {
                        "type": "string",
                        "description": (
                            "ISO YYYY-MM-DD or relative token; defaults to"
                            " due_date when omitted."
                        ),
                    },
                },
                "required": ["block_uuid", "due_date"],
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
