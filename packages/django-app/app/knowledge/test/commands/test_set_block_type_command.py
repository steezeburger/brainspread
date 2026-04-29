import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from knowledge.commands import SetBlockTypeCommand
from knowledge.forms import SetBlockTypeForm
from knowledge.models import Block, Page

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
        from django.utils import timezone

        block = self._make_block(
            content="DONE ship it",
            block_type="done",
            completed_at=timezone.now(),
        )
        result = self._run(block, "todo")
        assert result.block_type == "todo"
        assert result.completed_at is None

    def test_clears_completed_at_on_transition_out_of_wontdo(self):
        from django.utils import timezone

        block = self._make_block(
            content="WONTDO ship it",
            block_type="wontdo",
            completed_at=timezone.now(),
        )
        result = self._run(block, "todo")
        assert result.completed_at is None

    def test_preserves_completed_at_when_staying_completed(self):
        from django.utils import timezone

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
