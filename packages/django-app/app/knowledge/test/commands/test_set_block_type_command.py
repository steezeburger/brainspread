from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from knowledge.commands import SetBlockTypeCommand
from knowledge.forms import SetBlockTypeForm
from knowledge.models import Block, Page, Reminder

User = get_user_model()


@pytest.mark.django_db
class TestSetBlockTypeCommand:
    """SetBlockTypeCommand maintains completed_at and the content prefix."""

    def _make_block(self, **kwargs) -> Block:
        user = kwargs.pop("user", None) or User.objects.create_user(
            email="test@example.com", password="password"
        )
        page = Page.objects.create(title="Test Page", user=user)
        defaults = {
            "page": page,
            "user": user,
            "content": "Test",
            "block_type": "bullet",
            "order": 0,
        }
        defaults.update(kwargs)
        return Block.objects.create(**defaults)

    def _run(self, block: Block, new_type: str) -> Block:
        form = SetBlockTypeForm(
            {
                "user": block.user.id,
                "block": str(block.uuid),
                "block_type": new_type,
            }
        )
        assert form.is_valid(), form.errors
        return SetBlockTypeCommand(form).execute()

    def test_sets_completed_at_on_transition_to_done(self):
        block = self._make_block(content="TODO ship it", block_type="todo")
        result = self._run(block, "done")
        assert result.block_type == "done"
        assert result.completed_at is not None

    def test_sets_completed_at_on_transition_to_wontdo(self):
        block = self._make_block(content="LATER ship it", block_type="later")
        result = self._run(block, "wontdo")
        assert result.block_type == "wontdo"
        assert result.completed_at is not None

    def test_clears_completed_at_on_transition_out_of_done(self):
        block = self._make_block(
            content="DONE ship it",
            block_type="done",
            completed_at=timezone.now(),
        )
        result = self._run(block, "todo")
        assert result.block_type == "todo"
        assert result.completed_at is None

    def test_clears_completed_at_on_transition_out_of_wontdo(self):
        block = self._make_block(
            content="WONTDO ship it",
            block_type="wontdo",
            completed_at=timezone.now(),
        )
        result = self._run(block, "todo")
        assert result.completed_at is None

    def test_preserves_completed_at_when_staying_completed(self):
        original = timezone.now()
        block = self._make_block(
            content="DONE ship it",
            block_type="done",
            completed_at=original,
        )
        result = self._run(block, "wontdo")
        assert result.block_type == "wontdo"
        # both done and wontdo are terminal, so completed_at should be preserved
        assert result.completed_at == original

    def test_noop_when_setting_same_type(self):
        block = self._make_block(content="TODO ship", block_type="todo")
        result = self._run(block, "todo")
        assert result.block_type == "todo"
        assert result.content == "TODO ship"
        assert result.completed_at is None

    def test_swaps_content_prefix_between_states(self):
        block = self._make_block(content="TODO write docs", block_type="todo")
        result = self._run(block, "doing")
        assert result.content == "DOING write docs"

    def test_prepends_prefix_when_leaving_bullet(self):
        block = self._make_block(content="write docs", block_type="bullet")
        result = self._run(block, "todo")
        assert result.content == "TODO write docs"

    def test_strips_prefix_when_returning_to_bullet(self):
        block = self._make_block(content="DONE write docs", block_type="done")
        result = self._run(block, "bullet")
        assert result.content == "write docs"
        assert result.completed_at is None

    def test_skips_pending_reminders_when_entering_done(self):
        block = self._make_block(content="TODO ship it", block_type="todo")
        future = timezone.now() + timedelta(hours=1)
        reminder = Reminder.objects.create(block=block, fire_at=future)

        self._run(block, "done")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_SKIPPED

    def test_skips_pending_reminders_when_entering_wontdo(self):
        block = self._make_block(content="TODO ship it", block_type="todo")
        future = timezone.now() + timedelta(hours=1)
        reminder = Reminder.objects.create(block=block, fire_at=future)

        self._run(block, "wontdo")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_SKIPPED

    def test_does_not_resurrect_skipped_reminders_when_leaving_done(self):
        block = self._make_block(
            content="DONE ship it",
            block_type="done",
            completed_at=timezone.now(),
        )
        future = timezone.now() + timedelta(hours=1)
        reminder = Reminder.objects.create(
            block=block, fire_at=future, status=Reminder.STATUS_SKIPPED
        )

        self._run(block, "todo")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_SKIPPED

    def test_does_not_touch_already_sent_reminders(self):
        block = self._make_block(content="TODO ship it", block_type="todo")
        past = timezone.now() - timedelta(hours=1)
        reminder = Reminder.objects.create(
            block=block,
            fire_at=past,
            status=Reminder.STATUS_SENT,
            sent_at=past,
        )

        self._run(block, "done")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_SENT

    def test_does_not_touch_failed_reminders(self):
        block = self._make_block(content="TODO ship it", block_type="todo")
        past = timezone.now() - timedelta(minutes=5)
        reminder = Reminder.objects.create(
            block=block,
            fire_at=past,
            status=Reminder.STATUS_FAILED,
            last_error="boom",
        )

        self._run(block, "done")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_FAILED

    def test_only_affects_reminders_on_the_completed_block(self):
        user = User.objects.create_user(email="multi@example.com", password="p")
        page_a = Page.objects.create(title="Page A", slug="page-a", user=user)
        page_b = Page.objects.create(title="Page B", slug="page-b", user=user)
        block_a = Block.objects.create(
            page=page_a, user=user, content="TODO a", block_type="todo", order=0
        )
        block_b = Block.objects.create(
            page=page_b, user=user, content="TODO b", block_type="todo", order=0
        )
        future = timezone.now() + timedelta(hours=1)
        reminder_a = Reminder.objects.create(block=block_a, fire_at=future)
        reminder_b = Reminder.objects.create(block=block_b, fire_at=future)

        self._run(block_a, "done")

        reminder_a.refresh_from_db()
        reminder_b.refresh_from_db()
        assert reminder_a.status == Reminder.STATUS_SKIPPED
        assert reminder_b.status == Reminder.STATUS_PENDING

    def test_does_not_skip_when_transitioning_between_terminal_states(self):
        block = self._make_block(
            content="DONE ship it",
            block_type="done",
            completed_at=timezone.now(),
        )
        # If a reminder is somehow still pending (e.g. created after completion),
        # a done -> wontdo transition shouldn't re-skip it — we only skip on the
        # transition into a terminal state, not on movement within them.
        future = timezone.now() + timedelta(hours=1)
        reminder = Reminder.objects.create(block=block, fire_at=future)

        self._run(block, "wontdo")

        reminder.refresh_from_db()
        assert reminder.status == Reminder.STATUS_PENDING

    def test_rejects_block_from_other_user(self):
        u1 = User.objects.create_user(email="u1@example.com", password="p")
        u2 = User.objects.create_user(email="u2@example.com", password="p")
        block = self._make_block(user=u1, block_type="todo")

        form = SetBlockTypeForm(
            {"user": u2.id, "block": str(block.uuid), "block_type": "done"}
        )
        # clean_block rejects cross-user access, so the form is invalid; the
        # command re-validates and raises.
        with pytest.raises(ValidationError, match="not found"):
            SetBlockTypeCommand(form).execute()
