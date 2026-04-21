from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import CreateBlockCommand, UpdateBlockCommand
from knowledge.forms import CreateBlockForm, UpdateBlockForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestUpdateBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)
        cls.block = BlockFactory(page=cls.page, user=cls.user)

    def test_should_auto_detect_todo_when_content_changes_to_todo_prefix(self):
        """Test that updating content to 'TODO:' changes block type to todo"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "TODO: Buy groceries",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "todo")
        self.assertEqual(updated_block.content, "TODO: Buy groceries")

    def test_should_auto_detect_todo_when_content_changes_to_checkbox_empty(self):
        """Test that updating content to '[ ]' changes block type to todo"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "[ ] Complete project",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "todo")

    def test_should_auto_detect_done_when_content_changes_to_checkbox_checked(self):
        """Test that updating content to '[x]' changes block type to done"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "[x] Finished task",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "done")

    def test_should_auto_detect_done_when_content_changes_to_unicode_checkbox(self):
        """Test that updating content to '☑' changes block type to done"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "☑ Unicode done item",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "done")

    def test_should_change_from_todo_to_done_via_content_update(self):
        """Test changing from TODO to DONE by updating content"""
        # First create a todo block
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO: Task to complete",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        create_command = CreateBlockCommand(form)
        todo_block = create_command.execute()
        self.assertEqual(todo_block.block_type, "todo")

        # Then update content to mark as done
        form_data = {
            "user": self.user.id,
            "block": str(todo_block.uuid),
            "content": "[x] Task completed",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        update_command = UpdateBlockCommand(form)
        updated_block = update_command.execute()

        self.assertEqual(updated_block.block_type, "done")
        self.assertEqual(updated_block.content, "[x] Task completed")

    def test_should_not_override_heading_block_type(self):
        """Test that auto-detection doesn't override heading type"""
        # Create a heading block
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "# Heading",
            "block_type": "heading",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        create_command = CreateBlockCommand(form)
        heading_block = create_command.execute()

        # Update content to TODO pattern - should NOT change type
        form_data = {
            "user": self.user.id,
            "block": str(heading_block.uuid),
            "content": "TODO: This should stay a heading",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "heading")

    def test_should_not_override_code_block_type(self):
        """Test that auto-detection doesn't override code type"""
        # Create a code block
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "console.log('hello')",
            "block_type": "code",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        create_command = CreateBlockCommand(form)
        code_block = create_command.execute()

        # Update content to TODO pattern - should NOT change type
        form_data = {
            "user": self.user.id,
            "block": str(code_block.uuid),
            "content": "[ ] This should stay code",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "code")

    def test_should_change_to_bullet_when_no_pattern_matches(self):
        """Test that todo/done block types change to bullet when content doesn't match patterns"""
        # Start with a todo block
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO: Original task",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        create_command = CreateBlockCommand(form)
        todo_block = create_command.execute()
        self.assertEqual(todo_block.block_type, "todo")

        # Update to regular content - should change to bullet type
        form_data = {
            "user": self.user.id,
            "block": str(todo_block.uuid),
            "content": "Just regular content now",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "bullet")

    def test_should_not_auto_detect_when_content_not_updated(self):
        """Test that auto-detection only happens when content is updated"""
        # Create a bullet block
        original_block = self.block

        # Update other field, not content
        form_data = {
            "user": self.user.id,
            "block": str(original_block.uuid),
            "order": 5,
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        # Block type should remain unchanged
        self.assertEqual(updated_block.block_type, "bullet")
        self.assertEqual(updated_block.order, 5)

    def test_should_handle_empty_content_update(self):
        """Test that updating to empty content preserves block type"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.block_type, "bullet")
        self.assertEqual(updated_block.content, "")

    def test_should_raise_validation_error_for_nonexistent_block(self):
        """Test that updating nonexistent block raises ValidationError"""
        form_data = {
            "user": self.user.id,
            "block": "nonexistent-uuid",
            "content": "New content",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)

        with self.assertRaises(ValidationError):
            command.execute()

    def test_should_be_case_insensitive_for_todo_detection(self):
        """Test that TODO detection is case insensitive in updates"""
        test_cases = [
            ("todo: lowercase", "todo"),
            ("TODO: uppercase", "todo"),
            ("Todo: mixed case", "todo"),
        ]

        for content, expected_type in test_cases:
            with self.subTest(content=content):
                form_data = {
                    "user": self.user.id,
                    "block": str(self.block.uuid),
                    "content": content,
                }
                form = UpdateBlockForm(form_data)
                form.is_valid()
                command = UpdateBlockCommand(form)
                updated_block = command.execute()
                self.assertEqual(updated_block.block_type, expected_type)

    @patch("knowledge.commands.update_block_command.SyncBlockTagsCommand")
    def test_should_call_set_tags_from_content_when_content_updated(
        self, mock_sync_command_class
    ):
        """Test that tags are extracted when content is updated"""
        mock_sync_command = Mock()
        mock_sync_command_class.return_value = mock_sync_command

        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "TODO: Buy #groceries and #food",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        # Verify that SyncBlockTagsCommand was instantiated and executed
        mock_sync_command_class.assert_called_once()
        mock_sync_command.execute.assert_called_once()

    @patch("knowledge.commands.update_block_command.SyncBlockTagsCommand")
    def test_should_not_call_set_tags_from_content_when_content_not_updated(
        self, mock_sync_command_class
    ):
        """Test that tag extraction is skipped when content isn't updated"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "order": 10,
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        updated_block = command.execute()

        # Verify that SyncBlockTagsCommand was not called when content wasn't updated
        mock_sync_command_class.assert_not_called()

    @patch("knowledge.commands.update_block_command.SyncBlockTagsCommand")
    def test_should_skip_tag_extraction_for_code_blocks(
        self, mock_sync_command_class
    ):
        """Updating a code block shouldn't trigger tag sync on code content"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "#include <stdio.h>\nint main() {}",
            "block_type": "code",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        command.execute()

        mock_sync_command_class.assert_not_called()

    def test_should_preserve_properties_for_code_blocks(self):
        """Code block properties survive the no-key-extraction path on update"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "x = 1\nkey:: value",
            "block_type": "code",
            "properties": {"language": "python"},
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        block = command.execute()

        block.refresh_from_db()
        self.assertEqual(block.block_type, "code")
        self.assertEqual(block.properties, {"language": "python"})
