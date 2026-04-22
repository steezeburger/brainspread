"""Execute assistant-requested notes tool calls.

Keeps the `get_tool_result` surface small and JSON-serialisable so the
provider service can feed it straight back as a `tool_result` block.

Write tools (create_block / edit_block / move_blocks) never run without
explicit user approval — the service pauses and the execution happens
out-of-band during resume. See ai_chat.commands.resume_approval_command.
"""

import logging
from typing import Any, Dict, List

from core.models import User
from knowledge.commands.create_block_command import CreateBlockCommand
from knowledge.commands.create_page_command import CreatePageCommand
from knowledge.commands.update_block_command import UpdateBlockCommand
from knowledge.forms.create_block_form import CreateBlockForm
from knowledge.forms.create_page_form import CreatePageForm
from knowledge.forms.update_block_form import UpdateBlockForm
from knowledge.repositories.block_repository import BlockRepository
from knowledge.repositories.page_repository import PageRepository

from .notes_tools import (
    NOTES_READ_TOOL_NAMES,
    NOTES_WRITE_TOOL_NAMES,
)

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 25


class NotesToolExecutor:
    """Dispatches a custom tool call against the user's knowledge graph.

    `allow_writes` controls whether write tools are known at all. The
    service additionally calls `requires_approval(name)` before executing
    and pauses the tool loop when it returns True — writes only run after
    the user confirms them in the approval UI.
    """

    def __init__(self, user: User, allow_writes: bool = False) -> None:
        self.user = user
        self.allow_writes = allow_writes

    def is_known(self, name: str) -> bool:
        if name in NOTES_READ_TOOL_NAMES:
            return True
        if self.allow_writes and name in NOTES_WRITE_TOOL_NAMES:
            return True
        return False

    def requires_approval(self, name: str) -> bool:
        return name in NOTES_WRITE_TOOL_NAMES

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "search_notes":
                return self._search_notes(args)
            if name == "get_page_by_title":
                return self._get_page_by_title(args)
            if name == "get_block_by_id":
                return self._get_block_by_id(args)
            if name == "create_page":
                return self._create_page(args)
            if name == "create_block":
                return self._create_block(args)
            if name == "edit_block":
                return self._edit_block(args)
            if name == "move_blocks":
                return self._move_blocks(args)
            return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.exception("Notes tool %s failed", name)
            return {"error": f"Tool {name} failed: {e}"}

    def _search_notes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}

        raw_limit = args.get("limit") or DEFAULT_SEARCH_LIMIT
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = DEFAULT_SEARCH_LIMIT
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))

        blocks = (
            BlockRepository.search_by_content(self.user, query)
            .select_related("page")
            .order_by("-modified_at")[:limit]
        )
        results: List[Dict[str, Any]] = []
        for block in blocks:
            results.append(
                {
                    "block_uuid": str(block.uuid),
                    "page_title": block.page.title if block.page else None,
                    "page_slug": block.page.slug if block.page else None,
                    "block_type": block.block_type,
                    "content": block.content,
                }
            )
        return {"query": query, "count": len(results), "results": results}

    def _get_page_by_title(self, args: Dict[str, Any]) -> Dict[str, Any]:
        title = (args.get("title") or "").strip()
        if not title:
            return {"error": "title is required"}

        page = (
            PageRepository.get_queryset()
            .filter(user=self.user, title__iexact=title)
            .first()
        )
        if not page:
            return {"error": f"No page found with title '{title}'"}

        root_blocks = BlockRepository.get_root_blocks(page)
        return {
            "page": {
                "uuid": str(page.uuid),
                "title": page.title,
                "slug": page.slug,
                "page_type": page.page_type,
            },
            "blocks": [
                {
                    "block_uuid": str(block.uuid),
                    "block_type": block.block_type,
                    "content": block.content,
                    "order": block.order,
                }
                for block in root_blocks
            ],
        }

    def _get_block_by_id(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}

        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        children = BlockRepository.get_child_blocks(block)
        return {
            "block": {
                "block_uuid": str(block.uuid),
                "block_type": block.block_type,
                "content": block.content,
                "page_title": block.page.title if block.page else None,
                "page_slug": block.page.slug if block.page else None,
            },
            "children": [
                {
                    "block_uuid": str(child.uuid),
                    "block_type": child.block_type,
                    "content": child.content,
                    "order": child.order,
                }
                for child in children
            ],
        }

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
                "content": block.content,
                "block_type": block.block_type,
                "order": block.order,
            },
        }

    def _edit_block(self, args: Dict[str, Any]) -> Dict[str, Any]:
        block_uuid = (args.get("block_uuid") or "").strip()
        if not block_uuid:
            return {"error": "block_uuid is required"}
        content = args.get("content")
        if content is None:
            return {"error": "content is required"}

        block = BlockRepository.get_by_uuid(block_uuid, user=self.user)
        if not block:
            return {"error": f"No block found with uuid {block_uuid}"}

        form_data = {
            "user": self.user.id,
            "block": block.uuid,
            "content": content,
        }
        block_type = args.get("block_type")
        if block_type:
            form_data["block_type"] = block_type
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
            },
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
        for uuid_value in block_uuids:
            block = BlockRepository.get_by_uuid(str(uuid_value).strip(), user=self.user)
            if block is None:
                missing.append(str(uuid_value))
            else:
                blocks.append(block)
        if missing:
            return {"error": f"Blocks not found: {', '.join(missing)}"}

        ok = BlockRepository.move_blocks_to_page(blocks, target_page)
        if not ok:
            return {"error": "Move failed"}
        return {
            "moved": True,
            "count": len(blocks),
            "target_page_uuid": str(target_page.uuid),
        }


def _first_form_error(form) -> str:
    errors = form.errors
    if not errors:
        return "validation failed"
    first_field, field_errors = next(iter(errors.items()))
    if field_errors:
        return f"{first_field}: {field_errors[0]}"
    return "validation failed"
