"""Handlers for the assistant's notes tools.

Each handler is a thin adapter over a Form + Command pair: it shapes the
LLM-supplied args into form data (including parsing relative date tokens
like 'tomorrow' / '+7d'), runs the command, and shapes the result back
out. All business logic lives in the commands themselves.

Handlers take a ``ToolContext`` (the acting user plus optional
request-scoped state like the open page) and the raw args dict, and
return a JSON-serializable dict. On bad input they return
``{"error": ...}`` so the model can recover. The ``READ_HANDLERS`` /
``WRITE_HANDLERS`` maps at the bottom are joined with the JSON schemas in
``notes_tools`` to build the registry.
"""

import re
from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from django.utils import timezone

from ai_chat.forms import GetChatHistorySummaryForm
from core.commands.get_current_time_command import GetCurrentTimeCommand
from core.commands.get_user_preferences_command import GetUserPreferencesCommand
from core.forms import GetCurrentTimeForm, GetUserPreferencesForm
from core.llm_tools import ToolContext
from core.llm_tools import parse_relative_date as _parse_relative_date
from core.models import User
from knowledge.commands.bulk_cancel_reminders_command import (
    BulkCancelRemindersCommand,
)
from knowledge.commands.bulk_clear_schedule_command import BulkClearScheduleCommand
from knowledge.commands.bulk_schedule_command import BulkScheduleCommand
from knowledge.commands.bulk_set_block_type_command import BulkSetBlockTypeCommand
from knowledge.commands.bulk_snooze_command import BulkSnoozeCommand
from knowledge.commands.cancel_reminder_command import CancelReminderCommand
from knowledge.commands.create_block_command import CreateBlockCommand
from knowledge.commands.create_blocks_bulk_command import CreateBlocksBulkCommand
from knowledge.commands.create_page_command import CreatePageCommand
from knowledge.commands.create_page_embedded_view_command import (
    CreatePageEmbeddedViewCommand,
)
from knowledge.commands.create_saved_view_command import CreateSavedViewCommand
from knowledge.commands.delete_page_embedded_view_command import (
    DeletePageEmbeddedViewCommand,
)
from knowledge.commands.delete_saved_view_command import DeleteSavedViewCommand
from knowledge.commands.duplicate_saved_view_command import DuplicateSavedViewCommand
from knowledge.commands.find_stale_todos_command import FindStaleTodosCommand
from knowledge.commands.get_backlinks_command import GetBacklinksCommand
from knowledge.commands.get_block_by_id_command import GetBlockByIdCommand
from knowledge.commands.get_completion_stats_command import GetCompletionStatsCommand
from knowledge.commands.get_current_page_command import GetCurrentPageCommand
from knowledge.commands.get_daily_pages_in_range_command import (
    GetDailyPagesInRangeCommand,
)
from knowledge.commands.get_page_by_title_or_slug_command import (
    GetPageByTitleOrSlugCommand,
)
from knowledge.commands.get_recent_activity_command import GetRecentActivityCommand
from knowledge.commands.get_saved_view_command import GetSavedViewCommand
from knowledge.commands.get_streaks_command import GetStreaksCommand
from knowledge.commands.get_tag_graph_command import GetTagGraphCommand
from knowledge.commands.list_overdue_blocks_command import ListOverdueBlocksCommand
from knowledge.commands.list_pending_reminders_command import (
    ListPendingRemindersCommand,
)
from knowledge.commands.list_saved_views_command import ListSavedViewsCommand
from knowledge.commands.list_scheduled_blocks_command import ListScheduledBlocksCommand
from knowledge.commands.move_block_to_daily_command import MoveBlockToDailyCommand
from knowledge.commands.run_saved_view_command import RunSavedViewCommand
from knowledge.commands.schedule_block_command import ScheduleBlockCommand
from knowledge.commands.search_notes_command import SearchNotesCommand
from knowledge.commands.set_block_completed_at_command import (
    SetBlockCompletedAtCommand,
)
from knowledge.commands.set_block_type_command import SetBlockTypeCommand
from knowledge.commands.snooze_block_command import SnoozeBlockCommand
from knowledge.commands.tag_blocks_command import TagBlocksCommand, UntagBlocksCommand
from knowledge.commands.update_block_command import UpdateBlockCommand
from knowledge.commands.update_saved_view_command import UpdateSavedViewCommand
from knowledge.forms.bulk_cancel_reminders_form import BulkCancelRemindersForm
from knowledge.forms.bulk_clear_schedule_form import BulkClearScheduleForm
from knowledge.forms.bulk_schedule_form import BulkScheduleForm
from knowledge.forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from knowledge.forms.bulk_snooze_form import BulkSnoozeForm
from knowledge.forms.cancel_reminder_form import CancelReminderForm
from knowledge.forms.create_block_form import CreateBlockForm
from knowledge.forms.create_blocks_bulk_form import CreateBlocksBulkForm
from knowledge.forms.create_page_embedded_view_form import (
    CreatePageEmbeddedViewForm,
)
from knowledge.forms.create_page_form import CreatePageForm
from knowledge.forms.create_saved_view_form import CreateSavedViewForm
from knowledge.forms.delete_page_embedded_view_form import (
    DeletePageEmbeddedViewForm,
)
from knowledge.forms.delete_saved_view_form import DeleteSavedViewForm
from knowledge.forms.duplicate_saved_view_form import DuplicateSavedViewForm
from knowledge.forms.find_stale_todos_form import FindStaleTodosForm
from knowledge.forms.get_backlinks_form import GetBacklinksForm
from knowledge.forms.get_block_by_id_form import GetBlockByIdForm
from knowledge.forms.get_completion_stats_form import GetCompletionStatsForm
from knowledge.forms.get_current_page_form import GetCurrentPageForm
from knowledge.forms.get_daily_pages_in_range_form import GetDailyPagesInRangeForm
from knowledge.forms.get_page_by_title_or_slug_form import GetPageByTitleOrSlugForm
from knowledge.forms.get_recent_activity_form import GetRecentActivityForm
from knowledge.forms.get_saved_view_form import GetSavedViewForm
from knowledge.forms.get_streaks_form import GetStreaksForm
from knowledge.forms.get_tag_graph_form import GetTagGraphForm
from knowledge.forms.list_overdue_blocks_form import ListOverdueBlocksForm
from knowledge.forms.list_pending_reminders_form import ListPendingRemindersForm
from knowledge.forms.list_saved_views_form import ListSavedViewsForm
from knowledge.forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from knowledge.forms.move_block_to_daily_form import MoveBlockToDailyForm
from knowledge.forms.run_saved_view_form import RunSavedViewForm
from knowledge.forms.schedule_block_form import ScheduleBlockForm
from knowledge.forms.search_notes_form import SearchNotesForm
from knowledge.forms.set_block_completed_at_form import SetBlockCompletedAtForm
from knowledge.forms.set_block_type_form import SetBlockTypeForm
from knowledge.forms.snooze_block_form import SnoozeBlockForm
from knowledge.forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
from knowledge.forms.update_block_form import UpdateBlockForm
from knowledge.forms.update_saved_view_form import UpdateSavedViewForm
from knowledge.models import Block
from knowledge.repositories.block_repository import BlockRepository
from knowledge.repositories.page_embedded_view_repository import (
    PageEmbeddedViewRepository,
)
from knowledge.repositories.page_repository import PageRepository

# ---- Read handlers (thin form -> command wrappers) ----


def _search_notes(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "query": (args.get("query") or "").strip(),
    }
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = SearchNotesForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return SearchNotesCommand(form).execute()


def _get_page_by_title_or_slug(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    form = GetPageByTitleOrSlugForm(
        {
            "user": ctx.user.id,
            "query": (args.get("query") or "").strip(),
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetPageByTitleOrSlugCommand(form).execute()


def _get_block_by_id(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = GetBlockByIdForm(
        {
            "user": ctx.user.id,
            "block_uuid": (args.get("block_uuid") or "").strip(),
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetBlockByIdCommand(form).execute()


def _get_current_time(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = GetCurrentTimeForm({"user": ctx.user.id})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetCurrentTimeCommand(form).execute()


def _list_overdue_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = ListOverdueBlocksForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return ListOverdueBlocksCommand(form).execute()


def _list_pending_reminders(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = ListPendingRemindersForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return ListPendingRemindersCommand(form).execute()


def _list_scheduled_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    today = ctx.user.today()
    try:
        start_date = _parse_relative_date(args.get("start_date"), today)
        end_date = _parse_relative_date(args.get("end_date"), today)
    except ValueError as e:
        return {"error": str(e)}

    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if start_date is not None:
        form_data["start_date"] = start_date.isoformat()
    if end_date is not None:
        form_data["end_date"] = end_date.isoformat()
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]

    form = ListScheduledBlocksForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return ListScheduledBlocksCommand(form).execute()


def _get_daily_pages_in_range(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    today = ctx.user.today()
    try:
        start_date = _parse_relative_date(args.get("start_date"), today)
        end_date = _parse_relative_date(args.get("end_date"), today)
    except ValueError as e:
        return {"error": str(e)}

    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if start_date is not None:
        form_data["start_date"] = start_date.isoformat()
    if end_date is not None:
        form_data["end_date"] = end_date.isoformat()

    form = GetDailyPagesInRangeForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetDailyPagesInRangeCommand(form).execute()


def _get_completion_stats(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    today = ctx.user.today()
    try:
        start_date = _parse_relative_date(args.get("start_date"), today)
        end_date = _parse_relative_date(args.get("end_date"), today)
    except ValueError as e:
        return {"error": str(e)}

    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if start_date is not None:
        form_data["start_date"] = start_date.isoformat()
    if end_date is not None:
        form_data["end_date"] = end_date.isoformat()

    form = GetCompletionStatsForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetCompletionStatsCommand(form).execute()


def _get_streaks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    today = ctx.user.today()
    try:
        as_of = _parse_relative_date(args.get("as_of"), today)
    except ValueError as e:
        return {"error": str(e)}

    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "kind": (args.get("kind") or "").strip().lower(),
    }
    if as_of is not None:
        form_data["as_of"] = as_of.isoformat()

    form = GetStreaksForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetStreaksCommand(form).execute()


def _find_stale_todos(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("older_than_days") is not None:
        form_data["older_than_days"] = args["older_than_days"]
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = FindStaleTodosForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return FindStaleTodosCommand(form).execute()


def _get_backlinks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "page": (args.get("page_uuid") or "").strip(),
    }
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = GetBacklinksForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetBacklinksCommand(form).execute()


def _get_tag_graph(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("min_shared") is not None:
        form_data["min_shared"] = args["min_shared"]
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = GetTagGraphForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetTagGraphCommand(form).execute()


def _get_recent_activity(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("kind") is not None:
        form_data["kind"] = args["kind"]
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    form = GetRecentActivityForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetRecentActivityCommand(form).execute()


def _get_chat_history_summary(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    # Lazy import — `ai_chat.commands.__init__` pulls in
    # ResumeApprovalCommand which in turn imports NotesToolExecutor;
    # resolving the command class at call time avoids that cycle.
    from ai_chat.commands.get_chat_history_summary_command import (
        GetChatHistorySummaryCommand,
    )

    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if args.get("limit") is not None:
        form_data["limit"] = args["limit"]
    # The executor doesn't track the active session uuid yet — when
    # we wire that through later, populate `exclude_session_id`
    # here so the active session drops out of the listing.
    form = GetChatHistorySummaryForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetChatHistorySummaryCommand(form).execute()


def _get_user_preferences(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = GetUserPreferencesForm({"user": ctx.user.id})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetUserPreferencesCommand(form).execute()


def _get_current_page(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    if not ctx.current_page_uuid:
        return {
            "error": (
                "no current page — the user is not on a page right"
                " now (or the chat surface didn't pass one)"
            )
        }
    form = GetCurrentPageForm({"user": ctx.user.id, "page": ctx.current_page_uuid})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return GetCurrentPageCommand(form).execute()


# ---- SavedView read handlers (issue #60) ----


def _list_saved_views(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = ListSavedViewsForm({"user": ctx.user.id})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    views = ListSavedViewsCommand(form).execute()
    return {"views": [v.to_dict() for v in views]}


def _get_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    slug = (args.get("slug") or "").strip() or None
    uuid = (args.get("uuid") or "").strip() or None
    if not slug and not uuid:
        return {"error": "pass either slug or uuid"}
    if slug and uuid:
        return {"error": "pass slug OR uuid, not both"}
    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if uuid:
        form_data["view_uuid"] = uuid
    else:
        form_data["view_slug"] = slug
    form = GetSavedViewForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    view = GetSavedViewCommand(form).execute()
    return view.to_dict()


def _run_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a saved view by slug/uuid OR a draft inline filter.

    For the draft path we don't persist anything — we synthesize an
    in-memory SavedView via the create/run cycle so the command's
    compile-then-execute logic still pins validation errors.
    """
    slug = (args.get("slug") or "").strip() or None
    uuid = (args.get("uuid") or "").strip() or None
    inline_filter = args.get("filter")
    sort = args.get("sort")
    limit = args.get("limit")

    identifiers = [bool(slug), bool(uuid), inline_filter is not None]
    if sum(identifiers) != 1:
        return {"error": ("pass exactly one of: slug, uuid, or filter (inline draft)")}

    if inline_filter is not None:
        # Draft path — compile + execute without saving. Mirrors what
        # RunSavedViewCommand does internally so the LLM can dry-run
        # before proposing a save.
        from django.core.exceptions import ValidationError

        from knowledge.services import query_engine

        if not isinstance(inline_filter, dict):
            return {"error": "filter must be an object"}
        if sort is not None and not isinstance(sort, list):
            return {"error": "sort must be an array"}
        try:
            compiled = query_engine.compile(
                inline_filter, user=ctx.user, sort=sort or []
            )
        except (query_engine.QueryEngineError, ValidationError) as exc:
            return {"error": f"filter compile error: {exc}"}
        try:
            cap = int(limit) if limit is not None else 25
        except (TypeError, ValueError):
            return {"error": "limit must be an integer"}
        cap = max(1, min(cap, 500))
        rows = list(
            BlockRepository.run_compiled_query(ctx.user, compiled, limit=cap + 1)
        )
        truncated = len(rows) > cap
        if truncated:
            rows = rows[:cap]
        return {
            "view": None,
            "count": len(rows),
            "results": [b.to_dict(include_page_context=True) for b in rows],
            "truncated": truncated,
        }

    form_data: Dict[str, Any] = {"user": ctx.user.id}
    if uuid:
        form_data["view_uuid"] = uuid
    else:
        form_data["view_slug"] = slug
    if limit is not None:
        form_data["limit"] = limit
    form = RunSavedViewForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return RunSavedViewCommand(form).execute()


def _list_page_embedded_views(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    page_uuid = (args.get("page_uuid") or "").strip() or None
    page_slug = (args.get("page_slug") or "").strip() or None
    if not page_uuid and not page_slug:
        return {"error": "pass either page_uuid or page_slug"}
    if page_uuid and page_slug:
        return {"error": "pass page_uuid OR page_slug, not both"}

    if page_uuid:
        page = PageRepository.get_by_uuid(page_uuid, user=ctx.user)
    else:
        page = PageRepository.get_by_slug(page_slug, ctx.user)
    if not page:
        return {"error": "page not found"}

    embeds = PageEmbeddedViewRepository.list_for_page(page)
    return {
        "page": {"uuid": str(page.uuid), "slug": page.slug, "title": page.title},
        "embeds": [e.to_dict() for e in embeds],
    }


# ---- Write handlers ----


def _create_page(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}

    page_type = (args.get("page_type") or "page").strip() or "page"
    # `daily` is keyed on a specific date and auto-created elsewhere;
    # synthesizing one here would produce a dateless daily the rest of
    # the app can't navigate. `whiteboard` needs a tldraw JSON snapshot
    # in Page.whiteboard_snapshot that the model can't produce.
    if page_type not in ("page", "template"):
        return {
            "error": (
                f"Cannot create a '{page_type}' page via this tool."
                " Use 'page' or 'template'."
            )
        }

    form = CreatePageForm(
        {
            "user": ctx.user.id,
            "title": title,
            "page_type": page_type,
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}

    page = CreatePageCommand(form).execute()
    return {
        "created": True,
        "page": {
            "uuid": str(page.uuid),
            "title": page.title,
            "slug": page.slug,
            "page_type": page.page_type,
        },
        "affected_page_uuids": [str(page.uuid)],
    }


def _create_block(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    page_uuid = (args.get("page_uuid") or "").strip()
    content = args.get("content") or ""
    if not page_uuid:
        return {"error": "page_uuid is required"}
    if not content.strip():
        return {"error": "content is required"}

    page = PageRepository.get_by_uuid(page_uuid, user=ctx.user)
    if not page:
        return {"error": f"No page found with uuid {page_uuid}"}

    parent = None
    parent_uuid = (args.get("parent_uuid") or "").strip()
    if parent_uuid:
        parent = BlockRepository.get_by_uuid(parent_uuid, user=ctx.user)
        if not parent:
            return {"error": f"Parent block {parent_uuid} not found"}
        if parent.page_id != page.id:
            return {"error": "parent block belongs to a different page"}

    order = args.get("order")
    if order is None:
        order = BlockRepository.get_max_order(page, parent) + 1
    else:
        try:
            order = int(order)
        except (TypeError, ValueError):
            order = BlockRepository.get_max_order(page, parent) + 1

    form_data = {
        "user": ctx.user.id,
        "page": page.uuid,
        "content": content,
        "block_type": args.get("block_type") or "bullet",
        "order": order,
        "created_via": Block.CREATED_VIA_AI_CHAT,
    }
    if parent is not None:
        form_data["parent"] = parent.uuid
    form = CreateBlockForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    block = CreateBlockCommand(form).execute()
    return {
        "created": True,
        "block": {
            "block_uuid": str(block.uuid),
            "page_uuid": str(page.uuid),
            "page_slug": page.slug,
            "content": block.content,
            "block_type": block.block_type,
            "order": block.order,
        },
        "affected_page_uuids": [str(page.uuid)],
    }


def _edit_block(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        return {"error": "block_uuid is required"}

    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        return {"error": f"No block found with uuid {block_uuid}"}

    # Build the form payload only from keys the caller actually sent.
    # UpdateBlockCommand has a quirk: when "parent" is missing from
    # cleaned_data it sets block.parent = None (orphans to root). So we
    # must always include the existing parent_uuid unless the caller is
    # explicitly re-parenting.
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block": block.uuid,
    }

    if "content" in args and args["content"] is not None:
        form_data["content"] = args["content"]

    block_type = args.get("block_type")
    if block_type:
        form_data["block_type"] = block_type

    order_value = args.get("order")
    if order_value is not None:
        try:
            form_data["order"] = int(order_value)
        except (TypeError, ValueError):
            return {"error": "order must be an integer"}

    if "parent_uuid" in args:
        new_parent_uuid = args["parent_uuid"]
        if new_parent_uuid in (None, "", "null"):
            # Explicitly root the block.
            form_data["parent"] = ""
        else:
            new_parent = BlockRepository.get_by_uuid(
                str(new_parent_uuid).strip(), user=ctx.user
            )
            if not new_parent:
                return {"error": f"Parent block {new_parent_uuid} not found"}
            if new_parent.page_id != block.page_id:
                return {"error": "parent block belongs to a different page"}
            form_data["parent"] = new_parent.uuid
    elif block.parent_id is not None:
        # Preserve current parent so UpdateBlockCommand doesn't orphan
        # this block when the caller only wanted to change content/type.
        form_data["parent"] = block.parent.uuid

    completed_at = args.get("completed_at")
    has_block_fields = len(form_data) > 2

    if not has_block_fields and completed_at is None:
        # Only user + block — nothing to update.
        return {"error": "no fields provided to update"}

    updated = block
    if has_block_fields:
        form = UpdateBlockForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        updated = UpdateBlockCommand(form).execute()

    # Apply completed_at last: when the same call also flips the block to
    # done/wontdo, UpdateBlockCommand has already stamped completed_at to
    # "now", and this override replaces it with the caller's value. The
    # block must be terminal (the form enforces it) — which it now is.
    if completed_at is not None:
        ca_form = SetBlockCompletedAtForm(
            {
                "user": ctx.user.id,
                "block": str(updated.uuid),
                "completed_at": completed_at,
            }
        )
        if not ca_form.is_valid():
            return {"error": _first_form_error(ca_form)}
        updated = SetBlockCompletedAtCommand(ca_form).execute()

    return {
        "updated": True,
        "block": {
            "block_uuid": str(updated.uuid),
            "content": updated.content,
            "block_type": updated.block_type,
            "parent_uuid": (str(updated.parent.uuid) if updated.parent else None),
            "order": updated.order,
            "completed_at": (
                updated.completed_at.isoformat() if updated.completed_at else None
            ),
            "page_uuid": str(updated.page.uuid) if updated.page else None,
        },
        "affected_page_uuids": ([str(updated.page.uuid)] if updated.page else []),
    }


def _reorder_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    items = args.get("blocks") or []
    if not isinstance(items, list) or not items:
        return {"error": "blocks must be a non-empty list"}

    reorder_payload: List[Dict[str, Any]] = []
    seen: set = set()
    for item in items:
        if not isinstance(item, dict):
            return {"error": "each blocks entry must be an object"}
        uuid_value = (item.get("block_uuid") or "").strip()
        if not uuid_value:
            return {"error": "each entry needs block_uuid"}
        if uuid_value in seen:
            return {"error": f"duplicate block_uuid {uuid_value}"}
        seen.add(uuid_value)
        order_value = item.get("order")
        try:
            order_int = int(order_value)
        except (TypeError, ValueError):
            return {"error": "each entry needs an integer order"}
        reorder_payload.append({"uuid": uuid_value, "order": order_int})

    ok = BlockRepository.reorder_blocks(reorder_payload, user=ctx.user)
    if not ok:
        # Repository returns False when ownership/lookup fails too.
        return {"error": "Reorder failed (block missing or not owned by user)"}

    # Collect the distinct pages these blocks belong to so the frontend
    # can refresh whichever page is currently open.
    affected = list(
        BlockRepository.get_queryset()
        .filter(uuid__in=[item["uuid"] for item in reorder_payload])
        .values_list("page__uuid", flat=True)
        .distinct()
    )
    return {
        "reordered": True,
        "count": len(reorder_payload),
        "affected_page_uuids": [str(u) for u in affected if u is not None],
    }


def _move_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuids = args.get("block_uuids") or []
    target_uuid = (args.get("target_page_uuid") or "").strip()
    if not block_uuids or not isinstance(block_uuids, list):
        return {"error": "block_uuids must be a non-empty list"}
    if not target_uuid:
        return {"error": "target_page_uuid is required"}

    target_page = PageRepository.get_by_uuid(target_uuid, user=ctx.user)
    if not target_page:
        return {"error": f"No page found with uuid {target_uuid}"}

    blocks = []
    missing: List[str] = []
    # Capture the source pages BEFORE the move so the frontend can refresh
    # whichever the user had open.
    source_page_uuids: set = set()
    for uuid_value in block_uuids:
        block = BlockRepository.get_by_uuid(str(uuid_value).strip(), user=ctx.user)
        if block is None:
            missing.append(str(uuid_value))
        else:
            blocks.append(block)
            if block.page is not None:
                source_page_uuids.add(str(block.page.uuid))
    if missing:
        return {"error": f"Blocks not found: {', '.join(missing)}"}

    ok = BlockRepository.move_blocks_to_page(blocks, target_page)
    if not ok:
        return {"error": "Move failed"}

    affected = source_page_uuids | {str(target_page.uuid)}
    return {
        "moved": True,
        "count": len(blocks),
        "target_page_uuid": str(target_page.uuid),
        "affected_page_uuids": sorted(affected),
    }


def _schedule_block(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        return {"error": "block_uuid is required"}
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        return {"error": f"No block found with uuid {block_uuid}"}

    today = ctx.user.today()
    try:
        due_date = _parse_relative_date(args.get("due_date"), today)
    except ValueError as e:
        return {"error": f"due_date: {e}"}
    if due_date is None:
        return {"error": ("due_date is required (use clear_schedule to unschedule)")}

    try:
        reminder_date = _parse_relative_date(args.get("reminder_date"), today)
    except ValueError as e:
        return {"error": f"reminder_date: {e}"}

    # Resolve reminder_time. A relative offset ("+3m", "+2h") wins
    # over reminder_date — if the offset crosses midnight the date
    # rolls forward with it.
    try:
        resolved_date, resolved_time = _resolve_reminder_time(
            args.get("reminder_time"), ctx.user
        )
    except ValueError as e:
        return {"error": f"reminder_time: {e}"}
    if resolved_date is not None:
        reminder_date = resolved_date

    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block": block.uuid,
        "due_date": due_date.isoformat(),
    }
    # Optional time-of-day; absent leaves the due all-day.
    if args.get("due_time"):
        form_data["due_time"] = args["due_time"]
    if reminder_date is not None:
        form_data["reminder_date"] = reminder_date.isoformat()
    if resolved_time:
        form_data["reminder_time"] = resolved_time

    form = ScheduleBlockForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    updated = ScheduleBlockCommand(form).execute()
    return {
        "scheduled": True,
        "block": updated.to_dict(include_page_context=True),
        "affected_page_uuids": ([str(updated.page.uuid)] if updated.page else []),
    }


def _clear_schedule(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        return {"error": "block_uuid is required"}
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        return {"error": f"No block found with uuid {block_uuid}"}

    # ScheduleBlockForm treats a missing due_date as "clear" (the
    # field is required=False; cleaned_data["due_date"] is None).
    form = ScheduleBlockForm(
        {
            "user": ctx.user.id,
            "block": block.uuid,
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    updated = ScheduleBlockCommand(form).execute()
    return {
        "cleared": True,
        "block": updated.to_dict(include_page_context=True),
        "affected_page_uuids": ([str(updated.page.uuid)] if updated.page else []),
    }


def _set_block_type(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    block_type = (args.get("block_type") or "").strip()
    if not block_uuid:
        return {"error": "block_uuid is required"}
    if not block_type:
        return {"error": "block_type is required"}
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        return {"error": f"No block found with uuid {block_uuid}"}

    form = SetBlockTypeForm(
        {
            "user": ctx.user.id,
            "block": block.uuid,
            "block_type": block_type,
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    updated = SetBlockTypeCommand(form).execute()
    return {
        "updated": True,
        "block": updated.to_dict(include_page_context=True),
        "affected_page_uuids": ([str(updated.page.uuid)] if updated.page else []),
    }


def _move_block_to_daily(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    block_uuid = (args.get("block_uuid") or "").strip()
    if not block_uuid:
        return {"error": "block_uuid is required"}
    block = BlockRepository.get_by_uuid(block_uuid, user=ctx.user)
    if not block:
        return {"error": f"No block found with uuid {block_uuid}"}

    today = ctx.user.today()
    try:
        target_date = _parse_relative_date(args.get("target_date"), today)
    except ValueError as e:
        return {"error": f"target_date: {e}"}

    # Capture source page so the chat surface can refresh both ends
    # after the move (the command itself doesn't return the source).
    source_page_uuid = str(block.page.uuid) if block.page else None

    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block": block.uuid,
    }
    if target_date is not None:
        form_data["target_date"] = target_date.isoformat()

    form = MoveBlockToDailyForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    result = MoveBlockToDailyCommand(form).execute()

    target_page_uuid = result["target_page"]["uuid"]
    affected = {target_page_uuid}
    if source_page_uuid:
        affected.add(source_page_uuid)
    return {
        "moved": result["moved"],
        "message": result["message"],
        "block": result["block"],
        "target_page": result["target_page"],
        "affected_page_uuids": sorted(affected),
    }


def _snooze_block(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block": (args.get("block_uuid") or "").strip(),
    }
    if args.get("days") is not None:
        form_data["days"] = args["days"]
    if args.get("hours") is not None:
        form_data["hours"] = args["hours"]
    form = SnoozeBlockForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return SnoozeBlockCommand(form).execute()


def _cancel_reminder(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = CancelReminderForm(
        {
            "user": ctx.user.id,
            "block": (args.get("block_uuid") or "").strip(),
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return CancelReminderCommand(form).execute()


def _bulk_set_block_type(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = BulkSetBlockTypeForm(
        {
            "user": ctx.user.id,
            "block_uuids": args.get("block_uuids") or [],
            "new_type": (args.get("new_type") or "").strip(),
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return BulkSetBlockTypeCommand(form).execute()


def _tag_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = TagBlocksForm(
        {
            "user": ctx.user.id,
            "block_uuids": args.get("block_uuids") or [],
            "page_uuids": args.get("page_uuids") or [],
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return TagBlocksCommand(form).execute()


def _untag_blocks(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = UntagBlocksForm(
        {
            "user": ctx.user.id,
            "block_uuids": args.get("block_uuids") or [],
            "page_uuids": args.get("page_uuids") or [],
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return UntagBlocksCommand(form).execute()


def _bulk_schedule(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    today = ctx.user.today()
    try:
        new_date = _parse_relative_date(args.get("new_date"), today)
    except ValueError as e:
        return {"error": f"new_date: {e}"}
    if new_date is None:
        return {"error": "new_date is required"}

    try:
        reminder_date = _parse_relative_date(args.get("reminder_date"), today)
    except ValueError as e:
        return {"error": f"reminder_date: {e}"}

    # `+Nm` / `+Nh` offsets resolve relative to NOW, so they're
    # computed once for the whole batch — not per-block. The
    # offset can also override reminder_date when it crosses
    # midnight (matches single schedule_block).
    try:
        resolved_date, resolved_time = _resolve_reminder_time(
            args.get("reminder_time"), ctx.user
        )
    except ValueError as e:
        return {"error": f"reminder_time: {e}"}
    if resolved_date is not None:
        reminder_date = resolved_date

    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block_uuids": args.get("block_uuids") or [],
        "new_date": new_date.isoformat(),
    }
    # Optional time-of-day; absent leaves the dues all-day.
    if args.get("new_time"):
        form_data["new_time"] = args["new_time"]
    if reminder_date is not None:
        form_data["reminder_date"] = reminder_date.isoformat()
    if resolved_time:
        form_data["reminder_time"] = resolved_time

    form = BulkScheduleForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return BulkScheduleCommand(form).execute()


def _create_blocks_bulk(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "blocks": args.get("blocks") or [],
        "created_via": Block.CREATED_VIA_AI_CHAT,
    }
    page_uuid = (args.get("page_uuid") or "").strip()
    parent_uuid = (args.get("parent_uuid") or "").strip()
    if page_uuid:
        form_data["page"] = page_uuid
    if parent_uuid:
        form_data["parent"] = parent_uuid
    form = CreateBlocksBulkForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return CreateBlocksBulkCommand(form).execute()


def _bulk_clear_schedule(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = BulkClearScheduleForm(
        {
            "user": ctx.user.id,
            "block_uuids": args.get("block_uuids") or [],
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return BulkClearScheduleCommand(form).execute()


def _bulk_cancel_reminders(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form = BulkCancelRemindersForm(
        {
            "user": ctx.user.id,
            "block_uuids": args.get("block_uuids") or [],
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return BulkCancelRemindersCommand(form).execute()


def _bulk_snooze(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "block_uuids": args.get("block_uuids") or [],
    }
    if args.get("days") is not None:
        form_data["days"] = args["days"]
    if args.get("hours") is not None:
        form_data["hours"] = args["hours"]
    form = BulkSnoozeForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    return BulkSnoozeCommand(form).execute()


# ---- SavedView + PageEmbeddedView write handlers (issue #60) ----


def _create_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "name": (args.get("name") or "").strip(),
        "filter": args.get("filter") or {},
    }
    for key in ("slug", "description"):
        value = args.get(key)
        if value is not None:
            form_data[key] = value
    if args.get("sort") is not None:
        form_data["sort"] = args["sort"]
    form = CreateSavedViewForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        view = CreateSavedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"created": True, "view": view.to_dict()}


def _update_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    view_uuid = (args.get("uuid") or "").strip()
    if not view_uuid:
        return {"error": "uuid is required"}
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "view_uuid": view_uuid,
    }
    for key in ("name", "slug", "description"):
        value = args.get(key)
        if value is not None:
            form_data[key] = value
    if args.get("filter") is not None:
        form_data["filter"] = args["filter"]
    if args.get("sort") is not None:
        form_data["sort"] = args["sort"]
    form = UpdateSavedViewForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        view = UpdateSavedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"updated": True, "view": view.to_dict()}


def _delete_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    view_uuid = (args.get("uuid") or "").strip()
    if not view_uuid:
        return {"error": "uuid is required"}
    form = DeleteSavedViewForm({"user": ctx.user.id, "view_uuid": view_uuid})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        DeleteSavedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"deleted": True, "uuid": view_uuid}


def _duplicate_saved_view(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    view_uuid = (args.get("uuid") or "").strip()
    if not view_uuid:
        return {"error": "uuid is required"}
    form_data: Dict[str, Any] = {
        "user": ctx.user.id,
        "view_uuid": view_uuid,
    }
    new_name = args.get("new_name")
    if new_name is not None:
        form_data["new_name"] = new_name
    form = DuplicateSavedViewForm(form_data)
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        clone = DuplicateSavedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"duplicated": True, "view": clone.to_dict()}


def _embed_view_on_page(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    page_uuid = (args.get("page_uuid") or "").strip()
    view_uuid = (args.get("saved_view_uuid") or "").strip()
    if not page_uuid or not view_uuid:
        return {"error": "page_uuid and saved_view_uuid are required"}
    form = CreatePageEmbeddedViewForm(
        {
            "user": ctx.user.id,
            "page_uuid": page_uuid,
            "saved_view_uuid": view_uuid,
        }
    )
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        embed = CreatePageEmbeddedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"embedded": True, "embed": embed.to_dict()}


def _delete_page_embed(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from django.core.exceptions import ValidationError

    embed_uuid = (args.get("embed_uuid") or "").strip()
    if not embed_uuid:
        return {"error": "embed_uuid is required"}
    form = DeletePageEmbeddedViewForm({"user": ctx.user.id, "embed_uuid": embed_uuid})
    if not form.is_valid():
        return {"error": _first_form_error(form)}
    try:
        DeletePageEmbeddedViewCommand(form).execute()
    except ValidationError as exc:
        return {"error": str(exc)}
    return {"deleted": True, "embed_uuid": embed_uuid}


# ---- Date / time helpers ----

_RELATIVE_TIME_OFFSET_RE = re.compile(r"^([+-])(\d+)([mh])$")


def _resolve_reminder_time(
    value: Any, user: User
) -> Tuple[Optional[date], Optional[str]]:
    """Resolve a `reminder_time` arg into (date_override, 'HH:MM' or None).

    - Empty / None    -> (None, None) — caller should leave reminder unset.
    - 'HH:MM'         -> (None, 'HH:MM') — let the form parse it; the
                          caller's reminder_date / due_date fallback
                          decides which day it fires on.
    - '+Nm' / '+Nh'   -> (target_date, 'HH:MM') in the user's tz, computed
                          from now() + offset. The date is returned so the
                          caller can roll reminder_date forward when the
                          offset crosses midnight.
    """
    if value is None:
        return (None, None)
    text = str(value).strip().lower()
    if not text:
        return (None, None)

    match = _RELATIVE_TIME_OFFSET_RE.match(text)
    if match:
        sign, num, unit = match.groups()
        amount = int(num) * (1 if sign == "+" else -1)
        delta = timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)
        try:
            tz = pytz.timezone(user.timezone or "UTC")
        except pytz.UnknownTimeZoneError:
            tz = pytz.UTC
        target = timezone.now().astimezone(tz) + delta
        return (target.date(), target.strftime("%H:%M"))

    # Wall-clock — accept HH:MM or HH:MM:SS so we error early on garbage.
    # We return the original string; the form's TimeField parses it.
    try:
        time.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            f"expected HH:MM or '+Nm' / '+Nh' offset, got '{value}'"
        ) from e
    return (None, text)


def _first_form_error(form) -> str:
    errors = form.errors
    if not errors:
        return "validation failed"
    first_field, field_errors = next(iter(errors.items()))
    if field_errors:
        return f"{first_field}: {field_errors[0]}"
    return "validation failed"


# ---- Handler maps (joined with the JSON schemas in notes_tools) ----

READ_HANDLERS = {
    "search_notes": _search_notes,
    "get_page_by_title_or_slug": _get_page_by_title_or_slug,
    "get_block_by_id": _get_block_by_id,
    "get_current_time": _get_current_time,
    "list_overdue_blocks": _list_overdue_blocks,
    "list_pending_reminders": _list_pending_reminders,
    "get_daily_pages_in_range": _get_daily_pages_in_range,
    "get_completion_stats": _get_completion_stats,
    "get_streaks": _get_streaks,
    "get_backlinks": _get_backlinks,
    "get_tag_graph": _get_tag_graph,
    "get_recent_activity": _get_recent_activity,
    "get_chat_history_summary": _get_chat_history_summary,
    "get_user_preferences": _get_user_preferences,
    "get_current_page": _get_current_page,
    "find_stale_todos": _find_stale_todos,
    "list_scheduled_blocks": _list_scheduled_blocks,
    "list_saved_views": _list_saved_views,
    "get_saved_view": _get_saved_view,
    "run_saved_view": _run_saved_view,
    "list_page_embedded_views": _list_page_embedded_views,
}

WRITE_HANDLERS = {
    "create_page": _create_page,
    "create_block": _create_block,
    "edit_block": _edit_block,
    "reorder_blocks": _reorder_blocks,
    "move_blocks": _move_blocks,
    "schedule_block": _schedule_block,
    "clear_schedule": _clear_schedule,
    "set_block_type": _set_block_type,
    "move_block_to_daily": _move_block_to_daily,
    "snooze_block": _snooze_block,
    "cancel_reminder": _cancel_reminder,
    "bulk_set_block_type": _bulk_set_block_type,
    "tag_blocks": _tag_blocks,
    "untag_blocks": _untag_blocks,
    "bulk_schedule": _bulk_schedule,
    "create_blocks_bulk": _create_blocks_bulk,
    "bulk_clear_schedule": _bulk_clear_schedule,
    "bulk_cancel_reminders": _bulk_cancel_reminders,
    "bulk_snooze": _bulk_snooze,
    "create_saved_view": _create_saved_view,
    "update_saved_view": _update_saved_view,
    "delete_saved_view": _delete_saved_view,
    "duplicate_saved_view": _duplicate_saved_view,
    "embed_view_on_page": _embed_view_on_page,
    "delete_page_embed": _delete_page_embed,
}
