from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from knowledge.commands import SetBlockCompletedAtCommand
from knowledge.forms import SetBlockCompletedAtForm
from knowledge.models import Block, Page

User = get_user_model()


@pytest.mark.django_db
class TestSetBlockCompletedAtCommand:
    """SetBlockCompletedAtCommand overrides a terminal block's completed_at."""

    def _make_block(self, **kwargs) -> Block:
        user = kwargs.pop("user", None) or User.objects.create_user(
            email="test@example.com", password="password"
        )
        page = Page.objects.create(title="Test Page", user=user)
        defaults = {
            "page": page,
            "user": user,
            "content": "DONE ship it",
            "block_type": "done",
            "order": 0,
            "completed_at": timezone.now(),
        }
        defaults.update(kwargs)
        return Block.objects.create(**defaults)

    def _run(self, block: Block, completed_at: str) -> Block:
        form = SetBlockCompletedAtForm(
            {
                "user": block.user.id,
                "block": str(block.uuid),
                "completed_at": completed_at,
            }
        )
        assert form.is_valid(), form.errors
        return SetBlockCompletedAtCommand(form).execute()

    def test_sets_completed_at_on_done_block(self):
        block = self._make_block(block_type="done")
        result = self._run(block, "2026-06-20T09:00:00+00:00")
        assert result.completed_at == datetime(
            2026, 6, 20, 9, 0, 0, tzinfo=dt_timezone.utc
        )

    def test_sets_completed_at_on_wontdo_block(self):
        block = self._make_block(content="WONTDO nope", block_type="wontdo")
        result = self._run(block, "2026-06-20T09:00:00+00:00")
        assert result.completed_at == datetime(
            2026, 6, 20, 9, 0, 0, tzinfo=dt_timezone.utc
        )

    def test_naive_datetime_is_read_in_user_timezone(self):
        user = User.objects.create_user(
            email="tz@example.com", password="p", timezone="America/New_York"
        )
        block = self._make_block(user=user, block_type="done")
        # 09:00 EDT (UTC-4 in June) -> 13:00 UTC.
        result = self._run(block, "2026-06-20T09:00:00")
        assert result.completed_at == datetime(
            2026, 6, 20, 13, 0, 0, tzinfo=dt_timezone.utc
        )

    def test_persists_to_db(self):
        block = self._make_block(block_type="done")
        self._run(block, "2026-06-20T09:00:00+00:00")
        block.refresh_from_db()
        assert block.completed_at == datetime(
            2026, 6, 20, 9, 0, 0, tzinfo=dt_timezone.utc
        )

    def test_rejects_non_terminal_block(self):
        block = self._make_block(
            content="TODO ship it", block_type="todo", completed_at=None
        )
        form = SetBlockCompletedAtForm(
            {
                "user": block.user.id,
                "block": str(block.uuid),
                "completed_at": "2026-06-20T09:00:00+00:00",
            }
        )
        assert not form.is_valid()
        with pytest.raises(ValidationError):
            SetBlockCompletedAtCommand(form).execute()

    def test_rejects_invalid_datetime(self):
        block = self._make_block(block_type="done")
        form = SetBlockCompletedAtForm(
            {
                "user": block.user.id,
                "block": str(block.uuid),
                "completed_at": "not-a-date",
            }
        )
        assert not form.is_valid()
        assert "completed_at" in form.errors

    def test_rejects_block_from_other_user(self):
        u1 = User.objects.create_user(email="u1@example.com", password="p")
        u2 = User.objects.create_user(email="u2@example.com", password="p")
        block = self._make_block(user=u1, block_type="done")

        form = SetBlockCompletedAtForm(
            {
                "user": u2.id,
                "block": str(block.uuid),
                "completed_at": "2026-06-20T09:00:00+00:00",
            }
        )
        with pytest.raises(ValidationError, match="not found"):
            SetBlockCompletedAtCommand(form).execute()
