from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from assets.models import Asset
from knowledge.commands import CreateBlockCommand
from knowledge.forms import CreateBlockForm

from ..helpers import BlockFactory, PageFactory, UserFactory


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

    def test_should_auto_detect_done_from_done_prefix(self):
        """Blocks starting with 'DONE' are created as done type with
        completed_at stamped — otherwise they're invisible to completion
        queries since SetBlockTypeCommand only fires on transitions."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "DONE shipped the fix",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "done")
        self.assertIsNotNone(block.completed_at)

    def test_should_stamp_completed_at_for_explicit_done_block(self):
        """Explicit block_type=done also needs completed_at stamped at
        creation — the trigger isn't the DONE prefix, it's the terminal
        state."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "anything",
            "block_type": "done",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "done")
        self.assertIsNotNone(block.completed_at)

    def test_should_leave_completed_at_null_for_non_terminal_block(self):
        """Non-terminal types (bullet, todo, doing, later) don't get a
        completed_at stamp on creation."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "TODO write tests",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        command = CreateBlockCommand(form)
        block = command.execute()

        self.assertEqual(block.block_type, "todo")
        self.assertIsNone(block.completed_at)

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
    def test_should_skip_tag_extraction_for_code_blocks(self, mock_sync_command_class):
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

    def test_should_attach_asset_owned_by_caller(self):
        """A block can be created with a pre-uploaded asset attached."""
        asset = Asset.objects.create(
            user=self.user,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file_type=Asset.FILE_TYPE_IMAGE,
            mime_type="image/png",
        )
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "content_type": "image",
                "asset": str(asset.uuid),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        block = CreateBlockCommand(form).execute()

        self.assertEqual(block.asset_id, asset.id)
        self.assertEqual(block.content_type, "image")

    def test_should_reject_asset_owned_by_other_user(self):
        """Cross-user asset references must not pass validation."""
        other_user = UserFactory()
        asset = Asset.objects.create(
            user=other_user,
            asset_type=Asset.ASSET_TYPE_UPLOAD,
            file_type=Asset.FILE_TYPE_IMAGE,
        )
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "asset": str(asset.uuid),
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("asset", form.errors)

    def test_should_bump_page_modified_at(self):
        """Creating a block should advance the page's modified_at so it
        floats to the top of the recent-pages list."""
        original_modified_at = self.page.modified_at

        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "content": "fresh content",
            }
        )
        form.is_valid()
        CreateBlockCommand(form).execute()

        self.page.refresh_from_db()
        self.assertGreater(self.page.modified_at, original_modified_at)

    def test_created_via_defaults_to_web(self):
        """The web endpoint never sends created_via — the default stamp
        must read as human-authored."""
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "content": "typed by a human",
            }
        )
        form.is_valid()
        block = CreateBlockCommand(form).execute()

        self.assertEqual(block.created_via, "web")
        self.assertEqual(block.to_dict()["created_via"], "web")

    def test_created_via_honors_explicit_value(self):
        """Tool surfaces (AI chat, MCP) stamp their own provenance."""
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "content": "written by a tool",
                "created_via": "mcp",
            }
        )
        form.is_valid()
        block = CreateBlockCommand(form).execute()

        self.assertEqual(block.created_via, "mcp")

    def test_created_via_rejects_unknown_value(self):
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "content": "bogus source",
                "created_via": "carrier_pigeon",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("created_via", form.errors)


class TestCreateBlockTokenExpansion(TestCase):
    """Content {{tokens}} resolve at save and freeze (issue #140)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user, page_type="daily")

    def _create(self, content, page=None, **extra):
        form = CreateBlockForm(
            {
                "user": self.user.id,
                "page": (page or self.page).uuid,
                "content": content,
                **extra,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return CreateBlockCommand(form).execute()

    def test_should_expand_date_tokens_at_save(self):
        block = self._create("standup notes {{today}}")
        self.assertEqual(
            block.content, f"standup notes {self.user.today().isoformat()}"
        )

    def test_should_expand_page_tokens_against_source_page(self):
        block = self._create("on {{page.slug}}")
        self.assertEqual(block.content, f"on {self.page.slug}")

    def test_should_keep_tokens_dormant_on_template_pages(self):
        template = PageFactory(
            user=self.user, page_type="template", slug="tpl", title="Tpl"
        )
        block = self._create("standup notes {{today}}", page=template)
        self.assertEqual(block.content, "standup notes {{today}}")

    def test_should_skip_expansion_for_code_blocks(self):
        block = self._create("render({{today}})", block_type="code")
        self.assertEqual(block.content, "render({{today}})")

    def test_should_unescape_literal_braces(self):
        block = self._create("write \\{{today}} to insert the date")
        self.assertEqual(block.content, "write {{today}} to insert the date")

    def test_unknown_token_fails_loudly(self):
        with self.assertRaises(ValidationError) as caught:
            self._create("hello {{blorp}}")
        self.assertIn("{{blorp}}", str(caught.exception))
        self.assertIn("available tokens", str(caught.exception))

    def test_input_token_fails_at_block_save(self):
        with self.assertRaises(ValidationError) as caught:
            self._create("Project {{input:name}}")
        self.assertIn("applying a template", str(caught.exception))

    def test_count_token_freezes_a_number(self):
        BlockFactory(user=self.user, page=self.page, block_type="todo")
        BlockFactory(user=self.user, page=self.page, block_type="todo")
        block = self._create("open todos: {{count:type:todo and completed is null}}")
        self.assertEqual(block.content, "open todos: 2")

    def test_expanded_properties_are_extracted(self):
        block = self._create("carried:: {{today}}")
        self.assertEqual(block.properties.get("carried"), self.user.today().isoformat())
