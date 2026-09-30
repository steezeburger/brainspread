import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from knowledge.commands import BlockTodoToggleConflictError, ToggleBlockTodoCommand
from knowledge.forms import ToggleBlockTodoForm
from knowledge.models import Block, Page
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestToggleBlockTodoCommand:
    """Test the ToggleBlockTodoCommand"""

    def test_toggle_bullet_to_todo(self):
        """Test toggling a bullet block to todo"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page, user=user, content="Test block", block_type="bullet", order=0
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "todo"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "todo"

    def test_toggle_todo_to_doing(self):
        """Test toggling a todo block to doing"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page, user=user, content="Test todo", block_type="todo", order=0
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "doing"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "doing"

    def test_toggle_doing_to_done(self):
        """Test toggling a doing block to done"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page, user=user, content="Test doing", block_type="doing", order=0
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "done"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "done"

    def test_toggle_done_to_later(self):
        """Test toggling a done block to later"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page, user=user, content="Test done", block_type="done", order=0
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "later"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "later"

    def test_full_cycle_toggle(self):
        """Test the full cycle: bullet -> todo -> doing -> done -> later -> wontdo -> todo"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page, user=user, content="Test cycle", block_type="bullet", order=0
        )

        # bullet -> todo
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "todo"

        # todo -> doing
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "doing"

        # doing -> done
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "done"

        # done -> later
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "later"

        # later -> wontdo
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "wontdo"

        # wontdo -> todo
        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()
        assert result.block_type == "todo"

    def test_content_update_todo_to_doing(self):
        """Test that content is updated when toggling from todo to doing"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="TODO write documentation",
            block_type="todo",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "doing"
        assert result.content == "DOING write documentation"

        # Verify in database
        block.refresh_from_db()
        assert block.content == "DOING write documentation"

    def test_content_update_doing_to_done(self):
        """Test that content is updated when toggling from doing to done"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="DOING write documentation",
            block_type="doing",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "done"
        assert result.content == "DONE write documentation"

        # Verify in database
        block.refresh_from_db()
        assert block.content == "DONE write documentation"

    def test_content_update_done_to_later(self):
        """Test that content is updated when toggling from done to later"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="DONE write documentation",
            block_type="done",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "later"
        assert result.content == "LATER write documentation"

        # Verify in database
        block.refresh_from_db()
        assert block.content == "LATER write documentation"

    def test_content_with_colon_todo_to_doing(self):
        """Test that content with colon is updated correctly"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="TODO: write documentation",
            block_type="todo",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "doing"
        assert result.content == "DOING: write documentation"

    def test_toggle_nonexistent_block(self):
        """Test toggling a non-existent block raises ValidationError"""
        user = User.objects.create_user(email="test@example.com", password="password")

        with pytest.raises(ValidationError, match="not found"):
            # Use a valid UUID format that doesn't exist in the database
            nonexistent_uuid = str(uuid.uuid4())

            form_data = {"user": user.id, "block": nonexistent_uuid}
            form = ToggleBlockTodoForm(form_data)
            form.is_valid()
            command = ToggleBlockTodoCommand(form)
            command.execute()

    def test_toggle_later_to_wontdo(self):
        """Test toggling a later block to wontdo"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="LATER review code",
            block_type="later",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "wontdo"
        assert result.content == "WONTDO review code"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "wontdo"
        assert block.content == "WONTDO review code"

    def test_toggle_wontdo_to_todo(self):
        """Test toggling a wontdo block to todo"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="WONTDO review code",
            block_type="wontdo",
            order=0,
        )

        form_data = {"user": user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        result = command.execute()

        assert result.block_type == "todo"
        assert result.content == "TODO review code"

        # Verify in database
        block.refresh_from_db()
        assert block.block_type == "todo"
        assert block.content == "TODO review code"

    def test_toggle_unauthorized_block(self):
        """Test toggling a block owned by another user raises ValidationError"""
        user1 = User.objects.create_user(email="test1@example.com", password="password")
        user2 = User.objects.create_user(email="test2@example.com", password="password")

        page = Page.objects.create(title="Test Page", user=user1)
        block = Block.objects.create(
            page=page, user=user1, content="Test block", block_type="todo", order=0
        )

        with pytest.raises(ValidationError, match="Block not found"):
            form_data = {"user": user2.id, "block": str(block.uuid)}
            form = ToggleBlockTodoForm(form_data)
            form.is_valid()
            command = ToggleBlockTodoCommand(form)
            command.execute()

    def test_completed_at_set_when_cycling_to_done(self):
        """completed_at should be set when a block transitions into done"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="DOING write docs",
            block_type="doing",
            order=0,
        )
        assert block.completed_at is None

        form = ToggleBlockTodoForm({"user": user.id, "block": str(block.uuid)})
        form.is_valid()
        result = ToggleBlockTodoCommand(form).execute()

        assert result.block_type == "done"
        assert result.completed_at is not None

    def test_completed_at_cleared_when_cycling_out_of_done(self):
        """completed_at should be cleared when leaving done (done -> later)"""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="DONE write docs",
            block_type="done",
            order=0,
            completed_at=timezone.now(),
        )

        form = ToggleBlockTodoForm({"user": user.id, "block": str(block.uuid)})
        form.is_valid()
        result = ToggleBlockTodoCommand(form).execute()

        assert result.block_type == "later"
        assert result.completed_at is None

    def test_completed_at_preserved_when_cycling_done_to_wontdo(self):
        """Both done and wontdo are terminal — going later -> wontdo sets a
        new completed_at, but cycling between terminal states via the normal
        cycle (which goes done -> later first) is covered above. This test
        asserts wontdo receives a completed_at when cycling in."""
        user = User.objects.create_user(email="test@example.com", password="password")
        page = Page.objects.create(title="Test Page", user=user)
        block = Block.objects.create(
            page=page,
            user=user,
            content="LATER write docs",
            block_type="later",
            order=0,
        )

        form = ToggleBlockTodoForm({"user": user.id, "block": str(block.uuid)})
        form.is_valid()
        result = ToggleBlockTodoCommand(form).execute()

        assert result.block_type == "wontdo"
        assert result.completed_at is not None

    def test_toggle_succeeds_when_expected_from_type_matches(self):
        """expected_from_type matching the block's real type cycles normally."""
        user = UserFactory()
        page = PageFactory(user=user)
        block = BlockFactory(
            user=user, page=page, content="TODO write docs", block_type="todo"
        )

        form = ToggleBlockTodoForm(
            {
                "user": user.id,
                "block": str(block.uuid),
                "expected_from_type": "todo",
            }
        )
        assert form.is_valid()
        result = ToggleBlockTodoCommand(form).execute()

        assert result.block_type == "doing"
        assert result.content == "DOING write docs"

        block.refresh_from_db()
        assert block.block_type == "doing"

    def test_toggle_raises_conflict_when_expected_from_type_diverged(self):
        """Simulates the issue #236 scenario: the block was already cycled
        by another session (todo -> doing -> done) since this tab last saw
        it as "todo". Toggling with a stale expected_from_type must not
        cycle the block further (done -> later) — it should raise a
        conflict and leave the block exactly as the other session left it."""
        user = UserFactory()
        page = PageFactory(user=user)
        block = BlockFactory(
            user=user, page=page, content="DONE write docs", block_type="done"
        )

        form = ToggleBlockTodoForm(
            {
                "user": user.id,
                "block": str(block.uuid),
                # Stale — this tab still thinks the block is "todo".
                "expected_from_type": "todo",
            }
        )
        assert form.is_valid()

        with pytest.raises(BlockTodoToggleConflictError) as exc_info:
            ToggleBlockTodoCommand(form).execute()

        # The block was returned unchanged, not cycled from "done".
        conflict_block = exc_info.value.block
        assert conflict_block.block_type == "done"
        assert conflict_block.content == "DONE write docs"

        block.refresh_from_db()
        assert block.block_type == "done"
        assert block.content == "DONE write docs"

    def test_toggle_without_expected_from_type_ignores_conflict_check(self):
        """Omitting expected_from_type (existing MCP/AI-chat callers) keeps
        the old behavior: cycle from whatever the server's real type is."""
        user = UserFactory()
        page = PageFactory(user=user)
        block = BlockFactory(
            user=user, page=page, content="DONE write docs", block_type="done"
        )

        form = ToggleBlockTodoForm({"user": user.id, "block": str(block.uuid)})
        assert form.is_valid()
        result = ToggleBlockTodoCommand(form).execute()

        assert result.block_type == "later"
