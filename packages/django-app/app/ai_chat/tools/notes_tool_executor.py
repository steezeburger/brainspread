"""Execute assistant-requested notes tool calls.

Keeps the `get_tool_result` surface small and JSON-serialisable so the
provider service can feed it straight back as a `tool_result` block.
"""

import logging
from typing import Any, Dict, List

from core.models import User
from knowledge.repositories.block_repository import BlockRepository
from knowledge.repositories.page_repository import PageRepository

from .notes_tools import NOTES_TOOL_NAMES

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 25


class NotesToolExecutor:
    """Dispatches a custom tool call to a read-only knowledge query."""

    def __init__(self, user: User) -> None:
        self.user = user

    def is_known(self, name: str) -> bool:
        return name in NOTES_TOOL_NAMES

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "search_notes":
                return self._search_notes(args)
            if name == "get_page_by_title":
                return self._get_page_by_title(args)
            if name == "get_block_by_id":
                return self._get_block_by_id(args)
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
