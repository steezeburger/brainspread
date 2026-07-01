from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model

from ai_chat.tools.notes_handlers import _edit_block
from core.llm_tools import ToolContext
from knowledge.models import Block, Page
from mcp_server.tools import _edit_block as _mcp_edit_block

User = get_user_model()


@pytest.mark.django_db
class TestEditBlockCompletedAt:
    """edit_block (AI chat + MCP) folds in completed_at overrides."""

    def _setup(self, **block_kwargs) -> Block:
        user = User.objects.create_user(email="t@example.com", password="p")
        page = Page.objects.create(title="P", user=user)
        defaults = {
            "page": page,
            "user": user,
            "content": "DONE ship",
            "block_type": "done",
            "order": 0,
            "completed_at": datetime(2026, 6, 1, tzinfo=dt_timezone.utc),
        }
        defaults.update(block_kwargs)
        return Block.objects.create(**defaults)

    def test_ai_chat_sets_completed_at(self):
        block = self._setup()
        ctx = ToolContext(user=block.user)
        result = _edit_block(
            ctx,
            {
                "block_uuid": str(block.uuid),
                "completed_at": "2026-06-20T09:00:00+00:00",
            },
        )
        assert result.get("updated") is True
        block.refresh_from_db()
        assert block.completed_at == datetime(2026, 6, 20, 9, 0, tzinfo=dt_timezone.utc)

    def test_ai_chat_mark_done_and_set_time_in_one_call(self):
        block = self._setup(content="TODO ship", block_type="todo", completed_at=None)
        ctx = ToolContext(user=block.user)
        result = _edit_block(
            ctx,
            {
                "block_uuid": str(block.uuid),
                "block_type": "done",
                "completed_at": "2026-06-20T09:00:00+00:00",
            },
        )
        assert result.get("updated") is True
        block.refresh_from_db()
        assert block.block_type == "done"
        # The caller's timestamp wins over the auto "now" stamp.
        assert block.completed_at == datetime(2026, 6, 20, 9, 0, tzinfo=dt_timezone.utc)

    def test_ai_chat_rejects_completed_at_on_non_terminal(self):
        block = self._setup(content="TODO ship", block_type="todo", completed_at=None)
        ctx = ToolContext(user=block.user)
        result = _edit_block(
            ctx,
            {
                "block_uuid": str(block.uuid),
                "completed_at": "2026-06-20T09:00:00+00:00",
            },
        )
        assert "error" in result
        block.refresh_from_db()
        assert block.completed_at is None

    def test_mcp_sets_completed_at(self):
        block = self._setup()
        ctx = ToolContext(user=block.user)
        result = _mcp_edit_block(
            ctx,
            {
                "block_uuid": str(block.uuid),
                "completed_at": "2026-06-20T09:00:00+00:00",
            },
        )
        assert "block" in result
        block.refresh_from_db()
        assert block.completed_at == datetime(2026, 6, 20, 9, 0, tzinfo=dt_timezone.utc)
