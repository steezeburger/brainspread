from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from assets.models import Asset
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

    def test_should_stamp_completed_at_when_content_transitions_to_done(self):
        """Updating an empty bullet to start with 'DONE' must stamp
        completed_at. This is the real editor flow — Enter creates an
        empty bullet, then typing 'DONE shipped it' routes through
        UpdateBlockCommand. Without this stamp the block reads as done
        but stays invisible to 'done this week' queries."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        bullet = CreateBlockCommand(form).execute()
        self.assertEqual(bullet.block_type, "bullet")
        self.assertIsNone(bullet.completed_at)

        form_data = {
            "user": self.user.id,
            "block": str(bullet.uuid),
            "content": "DONE shipped it",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        updated = UpdateBlockCommand(form).execute()

        self.assertEqual(updated.block_type, "done")
        self.assertIsNotNone(updated.completed_at)

    def test_should_clear_completed_at_when_content_leaves_done(self):
        """The reverse: editing a done block's content so it no longer
        starts with 'DONE' must clear completed_at."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "DONE shipped it",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        done_block = CreateBlockCommand(form).execute()
        self.assertEqual(done_block.block_type, "done")
        self.assertIsNotNone(done_block.completed_at)

        form_data = {
            "user": self.user.id,
            "block": str(done_block.uuid),
            "content": "TODO actually still working on it",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        updated = UpdateBlockCommand(form).execute()

        self.assertEqual(updated.block_type, "todo")
        self.assertIsNone(updated.completed_at)

    def test_should_change_from_later_to_todo_via_content_update(self):
        """Editing "LATER x" to "TODO x" must move the type to todo. The
        later state is itself enterable by typing "LATER", so content
        edits have to be able to detect their way back out of it too."""
        later_block = BlockFactory(
            page=self.page,
            user=self.user,
            content="LATER write the report",
            block_type="later",
        )

        form_data = {
            "user": self.user.id,
            "block": str(later_block.uuid),
            "content": "TODO write the report",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        updated_block = UpdateBlockCommand(form).execute()

        self.assertEqual(updated_block.block_type, "todo")
        self.assertEqual(updated_block.content, "TODO write the report")

    def test_should_change_from_later_to_bullet_when_keyword_removed(self):
        """Removing the LATER keyword entirely demotes the block to a
        bullet, matching the todo/doing/done behavior."""
        later_block = BlockFactory(
            page=self.page,
            user=self.user,
            content="LATER write the report",
            block_type="later",
        )

        form_data = {
            "user": self.user.id,
            "block": str(later_block.uuid),
            "content": "write the report",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        updated_block = UpdateBlockCommand(form).execute()

        self.assertEqual(updated_block.block_type, "bullet")

    def test_should_clear_completed_at_when_content_leaves_wontdo(self):
        """wontdo is a terminal state — editing it back to "TODO x" must
        clear completed_at along with the type change."""
        form_data = {
            "user": self.user.id,
            "page": self.page.uuid,
            "content": "WONTDO chase that lead",
        }
        form = CreateBlockForm(form_data)
        form.is_valid()
        wontdo_block = CreateBlockCommand(form).execute()
        self.assertEqual(wontdo_block.block_type, "wontdo")
        self.assertIsNotNone(wontdo_block.completed_at)

        form_data = {
            "user": self.user.id,
            "block": str(wontdo_block.uuid),
            "content": "TODO chase that lead",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        updated_block = UpdateBlockCommand(form).execute()

        self.assertEqual(updated_block.block_type, "todo")
        self.assertIsNone(updated_block.completed_at)

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
    def test_should_skip_tag_extraction_for_code_blocks(self, mock_sync_command_class):
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

    def test_should_persist_collapsed_true(self):
        """Collapsing a block should persist to the database"""
        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "collapsed": True,
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        block = command.execute()

        block.refresh_from_db()
        self.assertTrue(block.collapsed)

    def test_should_persist_collapsed_false(self):
        """Expanding a previously collapsed block should persist to the database"""
        self.block.collapsed = True
        self.block.save()

        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "collapsed": False,
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        block = command.execute()

        block.refresh_from_db()
        self.assertFalse(block.collapsed)

    def test_should_not_change_collapsed_when_not_provided(self):
        """Updating other fields should not reset collapsed state"""
        self.block.collapsed = True
        self.block.save()

        form_data = {
            "user": self.user.id,
            "block": str(self.block.uuid),
            "content": "updated content",
        }
        form = UpdateBlockForm(form_data)
        form.is_valid()
        command = UpdateBlockCommand(form)
        block = command.execute()

        block.refresh_from_db()
        self.assertTrue(block.collapsed)
        self.assertEqual(block.content, "updated content")

    def test_should_attach_asset_to_existing_block(self):
        """Updating with an asset uuid attaches the asset to the block."""
        asset = Asset.objects.create(
            user=self.user,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file_type=Asset.FILE_TYPE_IMAGE,
            mime_type="image/png",
        )
        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "asset": str(asset.uuid),
                "content_type": "image",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        block = UpdateBlockCommand(form).execute()

        block.refresh_from_db()
        self.assertEqual(block.asset_id, asset.id)
        self.assertEqual(block.content_type, "image")

    def test_should_reject_asset_owned_by_other_user_on_update(self):
        other_user = UserFactory()
        asset = Asset.objects.create(
            user=other_user,
            asset_type=Asset.ASSET_TYPE_UPLOAD,
            file_type=Asset.FILE_TYPE_IMAGE,
        )
        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "asset": str(asset.uuid),
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("asset", form.errors)

    def test_should_detach_asset_when_explicitly_cleared(self):
        """Sending an empty asset clears the FK rather than ignoring it."""
        asset = Asset.objects.create(
            user=self.user,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file_type=Asset.FILE_TYPE_IMAGE,
        )
        self.block.asset = asset
        self.block.save()

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "asset": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        block = UpdateBlockCommand(form).execute()

        block.refresh_from_db()
        self.assertIsNone(block.asset_id)

    def test_should_leave_asset_alone_when_field_omitted(self):
        """Omitting `asset` from the payload must not reset an existing FK."""
        asset = Asset.objects.create(
            user=self.user,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file_type=Asset.FILE_TYPE_IMAGE,
        )
        self.block.asset = asset
        self.block.save()

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "content": "just touching content",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        block = UpdateBlockCommand(form).execute()

        block.refresh_from_db()
        self.assertEqual(block.asset_id, asset.id)

    def test_should_preserve_ui_managed_properties_on_content_edit(self):
        """A content edit must not clobber UI-managed properties (image
        resize width, "show as raw" render flag). Both live in the same
        JSON blob as content-derived `key:: value` properties, but they
        aren't represented in text, so the content-driven extractor that
        runs on every UpdateBlock has to leave them alone."""
        self.block.properties = {
            "size": {"width": 240},
            "render": "raw",
        }
        self.block.save()

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "content": "now with words but no key:: value syntax",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        UpdateBlockCommand(form).execute()

        self.block.refresh_from_db()
        self.assertEqual(self.block.properties.get("size"), {"width": 240})
        self.assertEqual(self.block.properties.get("render"), "raw")

    def test_should_merge_content_properties_with_ui_managed_ones(self):
        """When the user adds a `priority:: high` line to content, the
        extractor should add that key without dropping a previously
        set image width."""
        self.block.properties = {"size": {"width": 180}}
        self.block.save()

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(self.block.uuid),
                "content": "rework intro\npriority:: high",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        UpdateBlockCommand(form).execute()

        self.block.refresh_from_db()
        self.assertEqual(self.block.properties.get("priority"), "high")
        self.assertEqual(self.block.properties.get("size"), {"width": 180})

    def test_should_preserve_parent_on_properties_only_update(self):
        """A partial update that omits `parent` (e.g. the image resize
        handle persisting `properties.size`) must leave nesting alone.
        The command used to re-root the block whenever the key was
        missing, which silently flattened nested blocks on every
        properties-only save."""
        parent = BlockFactory(page=self.page, user=self.user)
        child = BlockFactory(page=self.page, user=self.user, parent=parent)

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(child.uuid),
                "properties": {"size": {"width": 320}},
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        UpdateBlockCommand(form).execute()

        child.refresh_from_db()
        self.assertEqual(child.parent_id, parent.id)
        self.assertEqual(child.properties.get("size"), {"width": 320})

    def test_should_clear_parent_on_explicit_null(self):
        """Submitting `parent: null` is still the outdent path — the
        omitted-key behavior above must not swallow explicit clears."""
        parent = BlockFactory(page=self.page, user=self.user)
        child = BlockFactory(page=self.page, user=self.user, parent=parent)

        form = UpdateBlockForm(
            {
                "user": self.user.id,
                "block": str(child.uuid),
                "parent": None,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        UpdateBlockCommand(form).execute()

        child.refresh_from_db()
        self.assertIsNone(child.parent_id)
