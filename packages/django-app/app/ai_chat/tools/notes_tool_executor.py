"""Execute assistant-requested notes tool calls.

Thin dispatcher: each tool call resolves to a Form + Command pair. The
executor's job is just argument-shape translation (LLM-shaped args ->
form data, including parsing relative date tokens like 'tomorrow' /
'+7d') plus the per-call approval gate for write tools. All business
logic lives in the commands themselves.

Write tools (create_block / edit_block / move_blocks / schedule_block /
clear_schedule / set_block_type / move_block_to_daily) never run without
explicit user approval — the service pauses and the execution happens
out-of-band during resume. See ai_chat.commands.resume_approval_command.
"""

import logging
import re
from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from django.utils import timezone

from core.commands.get_current_time_command import GetCurrentTimeCommand
from core.forms import GetCurrentTimeForm
from core.models import User
from knowledge.commands.bulk_cancel_reminders_command import (
    BulkCancelRemindersCommand,
)
from knowledge.commands.bulk_clear_schedule_command import BulkClearScheduleCommand
from knowledge.commands.bulk_reschedule_command import BulkRescheduleCommand
from knowledge.commands.bulk_set_block_type_command import BulkSetBlockTypeCommand
from knowledge.commands.bulk_snooze_command import BulkSnoozeCommand
from knowledge.commands.cancel_reminder_command import CancelReminderCommand
from knowledge.commands.create_block_command import CreateBlockCommand
from knowledge.commands.create_blocks_bulk_command import CreateBlocksBulkCommand
from knowledge.commands.create_page_command import CreatePageCommand
from knowledge.commands.find_stale_todos_command import FindStaleTodosCommand
from knowledge.commands.get_block_by_id_command import GetBlockByIdCommand
from knowledge.commands.get_completion_stats_command import GetCompletionStatsCommand
from knowledge.commands.get_current_page_command import GetCurrentPageCommand
from knowledge.commands.get_daily_pages_in_range_command import (
    GetDailyPagesInRangeCommand,
)
from knowledge.commands.get_page_by_title_command import GetPageByTitleCommand
from knowledge.commands.get_streaks_command import GetStreaksCommand
from knowledge.commands.list_overdue_blocks_command import ListOverdueBlocksCommand
from knowledge.commands.list_pending_reminders_command import (
    ListPendingRemindersCommand,
)
from knowledge.commands.list_scheduled_blocks_command import ListScheduledBlocksCommand
from knowledge.commands.move_block_to_daily_command import MoveBlockToDailyCommand
from knowledge.commands.schedule_block_command import ScheduleBlockCommand
from knowledge.commands.search_notes_command import SearchNotesCommand
from knowledge.commands.set_block_type_command import SetBlockTypeCommand
from knowledge.commands.snooze_block_command import SnoozeBlockCommand
from knowledge.commands.tag_blocks_command import TagBlocksCommand, UntagBlocksCommand
from knowledge.commands.update_block_command import UpdateBlockCommand
from knowledge.forms.bulk_cancel_reminders_form import BulkCancelRemindersForm
from knowledge.forms.bulk_clear_schedule_form import BulkClearScheduleForm
from knowledge.forms.bulk_reschedule_form import BulkRescheduleForm
from knowledge.forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from knowledge.forms.bulk_snooze_form import BulkSnoozeForm
from knowledge.forms.cancel_reminder_form import CancelReminderForm
from knowledge.forms.create_block_form import CreateBlockForm
from knowledge.forms.create_blocks_bulk_form import CreateBlocksBulkForm
from knowledge.forms.create_page_form import CreatePageForm
from knowledge.forms.find_stale_todos_form import FindStaleTodosForm
from knowledge.forms.get_block_by_id_form import GetBlockByIdForm
from knowledge.forms.get_completion_stats_form import GetCompletionStatsForm
from knowledge.forms.get_current_page_form import GetCurrentPageForm
from knowledge.forms.get_daily_pages_in_range_form import GetDailyPagesInRangeForm
from knowledge.forms.get_page_by_title_form import GetPageByTitleForm
from knowledge.forms.get_streaks_form import GetStreaksForm
from knowledge.forms.list_overdue_blocks_form import ListOverdueBlocksForm
from knowledge.forms.list_pending_reminders_form import ListPendingRemindersForm
from knowledge.forms.list_scheduled_blocks_form import ListScheduledBlocksForm
from knowledge.forms.move_block_to_daily_form import MoveBlockToDailyForm
from knowledge.forms.schedule_block_form import ScheduleBlockForm
from knowledge.forms.search_notes_form import SearchNotesForm
from knowledge.forms.set_block_type_form import SetBlockTypeForm
from knowledge.forms.snooze_block_form import SnoozeBlockForm
from knowledge.forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
from knowledge.forms.update_block_form import UpdateBlockForm
from knowledge.repositories.block_repository import BlockRepository
from knowledge.repositories.page_repository import PageRepository

from .notes_tools import (
    NOTES_READ_TOOL_NAMES,
    NOTES_WRITE_TOOL_NAMES,
)

logger = logging.getLogger(__name__)


class NotesToolExecutor:
    """Dispatches a custom tool call against the user's knowledge graph.

    `allow_writes` controls whether write tools are known at all.
    `auto_approve_writes` opts out of the per-call approval gate — writes
    execute inline like reads. This is opt-in per request; default keeps
    the safer manual-approval flow.
    """

    def __init__(
        self,
        user: User,
        allow_writes: bool = False,
        auto_approve_writes: bool = False,
        current_page_uuid: Optional[str] = None,
    ) -> None:
        self.user = user
        self.allow_writes = allow_writes
        self.auto_approve_writes = auto_approve_writes
        # Set by send_message_command from the chat request payload —
        # the page the user has open in the UI when they send a
        # message. Used by the get_current_page tool. None when the
        # user is on a non-page surface (graph view, etc).
        self.current_page_uuid = current_page_uuid

    def is_known(self, name: str) -> bool:
        if name in NOTES_READ_TOOL_NAMES:
            return True
        if self.allow_writes and name in NOTES_WRITE_TOOL_NAMES:
            return True
        return False

    def requires_approval(self, name: str) -> bool:
        if self.auto_approve_writes:
            return False
        return name in NOTES_WRITE_TOOL_NAMES

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "search_notes":
                return self._search_notes(args)
            if name == "get_page_by_title":
                return self._get_page_by_title(args)
            if name == "get_block_by_id":
                return self._get_block_by_id(args)
            if name == "get_current_time":
                return self._get_current_time(args)
            if name == "list_overdue_blocks":
                return self._list_overdue_blocks(args)
            if name == "list_pending_reminders":
                return self._list_pending_reminders(args)
            if name == "list_scheduled_blocks":
                return self._list_scheduled_blocks(args)
            if name == "get_daily_pages_in_range":
                return self._get_daily_pages_in_range(args)
            if name == "get_completion_stats":
                return self._get_completion_stats(args)
            if name == "get_streaks":
                return self._get_streaks(args)
            if name == "find_stale_todos":
                return self._find_stale_todos(args)
            if name == "get_current_page":
                return self._get_current_page(args)
            if name == "create_page":
                return self._create_page(args)
            if name == "create_block":
                return self._create_block(args)
            if name == "edit_block":
                return self._edit_block(args)
            if name == "move_blocks":
                return self._move_blocks(args)
            if name == "reorder_blocks":
                return self._reorder_blocks(args)
            if name == "schedule_block":
                return self._schedule_block(args)
            if name == "clear_schedule":
                return self._clear_schedule(args)
            if name == "set_block_type":
                return self._set_block_type(args)
            if name == "move_block_to_daily":
                return self._move_block_to_daily(args)
            if name == "snooze_block":
                return self._snooze_block(args)
            if name == "cancel_reminder":
                return self._cancel_reminder(args)
            if name == "bulk_set_block_type":
                return self._bulk_set_block_type(args)
            if name == "tag_blocks":
                return self._tag_blocks(args)
            if name == "untag_blocks":
                return self._untag_blocks(args)
            if name == "bulk_reschedule":
                return self._bulk_reschedule(args)
            if name == "create_blocks_bulk":
                return self._create_blocks_bulk(args)
            if name == "bulk_clear_schedule":
                return self._bulk_clear_schedule(args)
            if name == "bulk_cancel_reminders":
                return self._bulk_cancel_reminders(args)
            if name == "bulk_snooze":
                return self._bulk_snooze(args)
            return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.exception("Notes tool %s failed", name)
            return {"error": f"Tool {name} failed: {e}"}

    # ---- Read tools (thin form -> command wrappers) ----

    def _search_notes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {
            "user": self.user.id,
            "query": (args.get("query") or "").strip(),
        }
        if args.get("limit") is not None:
            form_data["limit"] = args["limit"]
        form = SearchNotesForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return SearchNotesCommand(form).execute()

    def _get_page_by_title(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = GetPageByTitleForm(
            {
                "user": self.user.id,
                "title": (args.get("title") or "").strip(),
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetPageByTitleCommand(form).execute()

    def _get_block_by_id(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = GetBlockByIdForm(
            {
                "user": self.user.id,
                "block_uuid": (args.get("block_uuid") or "").strip(),
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetBlockByIdCommand(form).execute()

    def _get_current_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = GetCurrentTimeForm({"user": self.user.id})
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetCurrentTimeCommand(form).execute()

    def _list_overdue_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {"user": self.user.id}
        if args.get("limit") is not None:
            form_data["limit"] = args["limit"]
        form = ListOverdueBlocksForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return ListOverdueBlocksCommand(form).execute()

    def _list_pending_reminders(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {"user": self.user.id}
        if args.get("limit") is not None:
            form_data["limit"] = args["limit"]
        form = ListPendingRemindersForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return ListPendingRemindersCommand(form).execute()

    def _list_scheduled_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        today = self.user.today()
        try:
            start_date = _parse_relative_date(args.get("start_date"), today)
            end_date = _parse_relative_date(args.get("end_date"), today)
        except ValueError as e:
            return {"error": str(e)}

        form_data: Dict[str, Any] = {"user": self.user.id}
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

    def _get_daily_pages_in_range(self, args: Dict[str, Any]) -> Dict[str, Any]:
        today = self.user.today()
        try:
            start_date = _parse_relative_date(args.get("start_date"), today)
            end_date = _parse_relative_date(args.get("end_date"), today)
        except ValueError as e:
            return {"error": str(e)}

        form_data: Dict[str, Any] = {"user": self.user.id}
        if start_date is not None:
            form_data["start_date"] = start_date.isoformat()
        if end_date is not None:
            form_data["end_date"] = end_date.isoformat()

        form = GetDailyPagesInRangeForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetDailyPagesInRangeCommand(form).execute()

    def _get_completion_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        today = self.user.today()
        try:
            start_date = _parse_relative_date(args.get("start_date"), today)
            end_date = _parse_relative_date(args.get("end_date"), today)
        except ValueError as e:
            return {"error": str(e)}

        form_data: Dict[str, Any] = {"user": self.user.id}
        if start_date is not None:
            form_data["start_date"] = start_date.isoformat()
        if end_date is not None:
            form_data["end_date"] = end_date.isoformat()

        form = GetCompletionStatsForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetCompletionStatsCommand(form).execute()

    def _get_streaks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        today = self.user.today()
        try:
            as_of = _parse_relative_date(args.get("as_of"), today)
        except ValueError as e:
            return {"error": str(e)}

        form_data: Dict[str, Any] = {
            "user": self.user.id,
            "kind": (args.get("kind") or "").strip().lower(),
        }
        if as_of is not None:
            form_data["as_of"] = as_of.isoformat()

        form = GetStreaksForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetStreaksCommand(form).execute()

    def _find_stale_todos(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {"user": self.user.id}
        if args.get("older_than_days") is not None:
            form_data["older_than_days"] = args["older_than_days"]
        if args.get("limit") is not None:
            form_data["limit"] = args["limit"]
        form = FindStaleTodosForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return FindStaleTodosCommand(form).execute()

    def _get_current_page(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.current_page_uuid:
            return {
                "error": (
                    "no current page — the user is not on a page right"
                    " now (or the chat surface didn't pass one)"
                )
            }
        form = GetCurrentPageForm(
            {"user": self.user.id, "page": self.current_page_uuid}
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return GetCurrentPageCommand(form).execute()

    # ---- Write tools ----

    def _create_page(self, args: Dict[str, Any]) -> Dict[str, Any]:
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
                "user": self.user.id,
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

    def _create_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        page_uuid = (args.get("page_uuid") or "").strip()
        content = args.get("content") or ""
        if not page_uuid:
            return {"error": "page_uuid is required"}
        if not content.strip():
            return {"error": "content is required"}

        page = PageRepository.get_by_uuid(page_uuid, user=self.user)
        if not page:
            return {"error": f"No page found with uuid {page_uuid}"}

        parent = None
        parent_uuid = (args.get("parent_uuid") or "").strip()
        if parent_uuid:
            parent = BlockRepository.get_by_uuid(parent_uuid, user=self.user)
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
            "user": self.user.id,
            "page": page.uuid,
            "content": content,
            "block_type": args.get("block_type") or "bullet",
            "order": order,
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

    def _edit_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}

        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        # Build the form payload only from keys the caller actually sent.
        # UpdateBlockCommand has a quirk: when "parent" is missing from
        # cleaned_data it sets block.parent = None (orphans to root). So we
        # must always include the existing parent_uuid unless the caller is
        # explicitly re-parenting.
        form_data: Dict[str, Any] = {
            "user": self.user.id,
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
                    str(new_parent_uuid).strip(), user=self.user
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

        if len(form_data) == 2:
            # Only user + block — nothing to update.
            return {"error": "no fields provided to update"}

        form = UpdateBlockForm(form_data)
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        updated = UpdateBlockCommand(form).execute()
        return {
            "updated": True,
            "block": {
                "block_uuid": str(updated.uuid),
                "content": updated.content,
                "block_type": updated.block_type,
                "parent_uuid": (str(updated.parent.uuid) if updated.parent else None),
                "order": updated.order,
                "page_uuid": str(updated.page.uuid) if updated.page else None,
            },
            "affected_page_uuids": ([str(updated.page.uuid)] if updated.page else []),
        }

    def _reorder_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
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

        ok = BlockRepository.reorder_blocks(reorder_payload, user=self.user)
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

    def _move_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuids = args.get("block_uuids") or []
        target_uuid = (args.get("target_page_uuid") or "").strip()
        if not block_uuids or not isinstance(block_uuids, list):
            return {"error": "block_uuids must be a non-empty list"}
        if not target_uuid:
            return {"error": "target_page_uuid is required"}

        target_page = PageRepository.get_by_uuid(target_uuid, user=self.user)
        if not target_page:
            return {"error": f"No page found with uuid {target_uuid}"}

        blocks = []
        missing: List[str] = []
        # Capture the source pages BEFORE the move so the frontend can refresh
        # whichever the user had open.
        source_page_uuids: set = set()
        for uuid_value in block_uuids:
            block = BlockRepository.get_by_uuid(str(uuid_value).strip(), user=self.user)
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

    def _schedule_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}
        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        today = self.user.today()
        try:
            scheduled_for = _parse_relative_date(args.get("scheduled_for"), today)
        except ValueError as e:
            return {"error": f"scheduled_for: {e}"}
        if scheduled_for is None:
            return {
                "error": (
                    "scheduled_for is required (use clear_schedule to unschedule)"
                )
            }

        try:
            reminder_date = _parse_relative_date(args.get("reminder_date"), today)
        except ValueError as e:
            return {"error": f"reminder_date: {e}"}

        # Resolve reminder_time. A relative offset ("+3m", "+2h") wins
        # over reminder_date — if the offset crosses midnight the date
        # rolls forward with it.
        try:
            resolved_date, resolved_time = _resolve_reminder_time(
                args.get("reminder_time"), self.user
            )
        except ValueError as e:
            return {"error": f"reminder_time: {e}"}
        if resolved_date is not None:
            reminder_date = resolved_date

        form_data: Dict[str, Any] = {
            "user": self.user.id,
            "block": block.uuid,
            "scheduled_for": scheduled_for.isoformat(),
        }
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

    def _clear_schedule(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}
        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        # ScheduleBlockForm treats a missing scheduled_for as "clear" (the
        # field is required=False; cleaned_data["scheduled_for"] is None).
        form = ScheduleBlockForm(
            {
                "user": self.user.id,
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

    def _set_block_type(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        block_type = (args.get("block_type") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}
        if not block_type:
            return {"error": "block_type is required"}
        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        form = SetBlockTypeForm(
            {
                "user": self.user.id,
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

    def _move_block_to_daily(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}
        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        today = self.user.today()
        try:
            target_date = _parse_relative_date(args.get("target_date"), today)
        except ValueError as e:
            return {"error": f"target_date: {e}"}

        # Capture source page so the chat surface can refresh both ends
        # after the move (the command itself doesn't return the source).
        source_page_uuid = str(block.page.uuid) if block.page else None

        form_data: Dict[str, Any] = {
            "user": self.user.id,
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

    def _snooze_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {
            "user": self.user.id,
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

    def _cancel_reminder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = CancelReminderForm(
            {
                "user": self.user.id,
                "block": (args.get("block_uuid") or "").strip(),
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return CancelReminderCommand(form).execute()

    def _bulk_set_block_type(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = BulkSetBlockTypeForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
                "new_type": (args.get("new_type") or "").strip(),
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return BulkSetBlockTypeCommand(form).execute()

    def _tag_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = TagBlocksForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
                "page_uuids": args.get("page_uuids") or [],
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return TagBlocksCommand(form).execute()

    def _untag_blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = UntagBlocksForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
                "page_uuids": args.get("page_uuids") or [],
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return UntagBlocksCommand(form).execute()

    def _bulk_reschedule(self, args: Dict[str, Any]) -> Dict[str, Any]:
        today = self.user.today()
        try:
            new_date = _parse_relative_date(args.get("new_date"), today)
        except ValueError as e:
            return {"error": f"new_date: {e}"}
        if new_date is None:
            return {"error": "new_date is required"}

        form = BulkRescheduleForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
                "new_date": new_date.isoformat(),
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return BulkRescheduleCommand(form).execute()

    def _create_blocks_bulk(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {
            "user": self.user.id,
            "blocks": args.get("blocks") or [],
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

    def _bulk_clear_schedule(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = BulkClearScheduleForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return BulkClearScheduleCommand(form).execute()

    def _bulk_cancel_reminders(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form = BulkCancelRemindersForm(
            {
                "user": self.user.id,
                "block_uuids": args.get("block_uuids") or [],
            }
        )
        if not form.is_valid():
            return {"error": _first_form_error(form)}
        return BulkCancelRemindersCommand(form).execute()

    def _bulk_snooze(self, args: Dict[str, Any]) -> Dict[str, Any]:
        form_data: Dict[str, Any] = {
            "user": self.user.id,
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


_RELATIVE_OFFSET_RE = re.compile(r"^([+-])(\d+)([dw])$")
_RELATIVE_TIME_OFFSET_RE = re.compile(r"^([+-])(\d+)([mh])$")


def _resolve_reminder_time(
    value: Any, user: User
) -> Tuple[Optional[date], Optional[str]]:
    """Resolve a `reminder_time` arg into (date_override, 'HH:MM' or None).

    - Empty / None    -> (None, None) — caller should leave reminder unset.
    - 'HH:MM'         -> (None, 'HH:MM') — let the form parse it; the
                          caller's reminder_date / scheduled_for fallback
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


def _parse_relative_date(value: Any, today: date) -> Optional[date]:
    """Parse a date input that accepts ISO YYYY-MM-DD or simple relative
    tokens ('today', 'tomorrow', 'yesterday', '+Nd', '-Nd', '+Nw', '-Nw').

    Returns None when the input is empty / missing. Raises ValueError on
    unrecognised formats so the caller can surface a helpful error.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text == "yesterday":
        return today - timedelta(days=1)
    match = _RELATIVE_OFFSET_RE.match(text)
    if match:
        sign, num, unit = match.groups()
        amount = int(num) * (1 if sign == "+" else -1)
        days = amount if unit == "d" else amount * 7
        return today + timedelta(days=days)
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(
            f"expected ISO YYYY-MM-DD or 'today'/'tomorrow'/'+Nd', got '{value}'"
        ) from e


def _first_form_error(form) -> str:
    errors = form.errors
    if not errors:
        return "validation failed"
    first_field, field_errors = next(iter(errors.items()))
    if field_errors:
        return f"{first_field}: {field_errors[0]}"
    return "validation failed"
