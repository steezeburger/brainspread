import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from knowledge.commands import ToggleBlockTodoCommand
from knowledge.forms import ToggleBlockTodoForm
from knowledge.models import Block, Page

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
