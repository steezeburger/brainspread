from unittest.mock import Mock, patch

from django.test import TestCase

from knowledge.commands import CreateBlockCommand
from knowledge.forms import CreateBlockForm

from ..helpers import PageFactory, UserFactory


class TestCreateBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_should_auto_detect_todo_from_todo_prefix(self):
        """Test that blocks starting with 'TODO' are created as todo type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO: Buy groceries",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "todo")
        self.assertEqual(block.content, "TODO: Buy groceries")

    def test_should_auto_detect_todo_from_checkbox_empty(self):
        """Test that blocks starting with '[ ]' are created as todo type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "[ ] Complete project",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "todo")

    def test_should_auto_detect_done_from_checkbox_checked(self):
        """Test that blocks starting with '[x]' are created as done type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "[x] Finished task",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "done")

    def test_should_auto_detect_todo_from_unicode_checkbox(self):
        """Test that blocks starting with '☐' are created as todo type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "☐ Unicode todo item",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "todo")

    def test_should_auto_detect_done_from_unicode_checkbox(self):
        """Test that blocks starting with '☑' are created as done type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "☑ Unicode done item",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "done")

    def test_should_not_override_explicit_block_type(self):
        """Test that explicit block_type is not overridden by auto-detection"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO: This should stay as heading",
            "block_type": "heading",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "heading")

    def test_should_default_to_bullet_for_regular_content(self):
        """Test that regular content defaults to bullet type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "Just a regular block",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "bullet")

    def test_should_handle_empty_content(self):
        """Test that empty content defaults to bullet type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "bullet")

    def test_should_handle_whitespace_only_content(self):
        """Test that whitespace-only content defaults to bullet type"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "   \n\t  ",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "bullet")

    def test_should_be_case_insensitive_for_todo_detection(self):
        """Test that TODO detection is case insensitive"""
        test_cases = [
            "todo: lowercase",
            "TODO: uppercase",
            "Todo: mixed case",
            "tOdO: weird case",
        ]

        for content in test_cases:
            with self.subTest(content=content):
                form_data = {
                    "user": self.user.id,
                    "page": self.page.uuid,
                    "content": content,
                }
                form = CreateBlockForm(form_data)
                form.is_valid()
                command = CreateBlockCommand(form)
                block = command.execute()
                self.assertEqual(block.block_type, "todo")

    @patch("knowledge.commands.create_block_command.SyncBlockTagsCommand")
    def test_should_call_set_tags_from_content_when_content_exists(
        self, mock_sync_command_class
    ):
        """Test that tags are extracted from block content"""
        mock_sync_command = Mock()
        mock_sync_command_class.return_value = mock_sync_command

        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO: Buy #groceries and #food",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        # Verify that SyncBlockTagsCommand was instantiated and executed
        mock_sync_command_class.assert_called_once()
        mock_sync_command.execute.assert_called_once()

    @patch("knowledge.commands.create_block_command.SyncBlockTagsCommand")
    def test_should_not_call_set_tags_from_content_when_no_content(
        self, mock_sync_command_class
    ):
        """Test that tag extraction is skipped for empty content"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        # Verify that SyncBlockTagsCommand was not called for empty content
        mock_sync_command_class.assert_not_called()

    @patch("knowledge.commands.create_block_command.SyncBlockTagsCommand")
    def test_should_skip_tag_extraction_for_code_blocks(
        self, mock_sync_command_class
    ):
        """Code block content (e.g. `#include <stdio.h>`) shouldn't trigger tag sync"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "#include <stdio.h>\nint main() {}",
            "block_type": "code",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        command.execute()

        mock_sync_command_class.assert_not_called()

    def test_should_preserve_properties_for_code_blocks(self):
        """Code block properties (e.g. language) survive the no-key-extraction path"""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "x = 1\nkey:: value",
            "block_type": "code",
            "properties": {"language": "python"},
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        block.refresh_from_db()
        self.assertEqual(block.block_type, "code")
        self.assertEqual(block.properties, {"language": "python"})
