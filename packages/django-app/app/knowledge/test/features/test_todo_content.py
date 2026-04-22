from django.test import TestCase

from knowledge.commands.toggle_block_todo_command import ToggleBlockTodoCommand
from knowledge.forms import ToggleBlockTodoForm
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class TestTodoContentIntegration(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_should_toggle_todo_content_with_text(self):
        """Test toggling todo content that contains additional text"""
        # Create a todo block with additional text
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="TODO google tasks integration",
            block_type="todo",
        )

        # Toggle to doing
        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        updated_block = command.execute()

        # Verify content and type changed
        self.assertEqual(updated_block.content, "DOING google tasks integration")
        self.assertEqual(updated_block.block_type, "doing")

        # Toggle to done (next state after doing)
        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command2 = ToggleBlockTodoCommand(form)
        updated_block2 = command2.execute()

        # Verify content and type changed to done
        self.assertEqual(updated_block2.content, "DONE google tasks integration")
        self.assertEqual(updated_block2.block_type, "done")

    def test_should_handle_todo_content_replacement_patterns(self):
        """Test various todo content replacement patterns (todo -> doing)"""
        test_cases = [
            ("TODO simple task", "DOING simple task"),
            ("TODO: task with colon", "DOING: task with colon"),
            ("todo lowercase", "DOING lowercase"),
            ("Todo mixed case", "DOING mixed case"),
        ]

        for original_content, expected_doing_content in test_cases:
            with self.subTest(content=original_content):
                # Create block with original content
                block = BlockFactory(
                    user=self.user,
                    page=self.page,
                    content=original_content,
                    block_type="todo",
                )

                # Toggle to doing
                form_data = {"user": self.user.id, "block": str(block.uuid)}
                form = ToggleBlockTodoForm(form_data)
                form.is_valid()
                command = ToggleBlockTodoCommand(form)
                updated_block = command.execute()

                # Verify content transformation
                self.assertEqual(updated_block.content, expected_doing_content)
                self.assertEqual(updated_block.block_type, "doing")

    def test_should_handle_done_content_replacement_patterns(self):
        """Test various done content replacement patterns - done goes to later first"""
        test_cases = [
            ("DONE simple task", "LATER simple task"),
            ("DONE: task with colon", "LATER: task with colon"),
            ("done lowercase", "LATER lowercase"),
            ("Done mixed case", "LATER mixed case"),
        ]

        for original_content, expected_later_content in test_cases:
            with self.subTest(content=original_content):
                # Create block with original content
                block = BlockFactory(
                    user=self.user,
                    page=self.page,
                    content=original_content,
                    block_type="done",
                )

                # Toggle to later (next state after done)
                form_data = {"user": self.user.id, "block": str(block.uuid)}
                form = ToggleBlockTodoForm(form_data)
                form.is_valid()
                command = ToggleBlockTodoCommand(form)
                updated_block = command.execute()

                # Verify content transformation
                self.assertEqual(updated_block.content, expected_later_content)
                self.assertEqual(updated_block.block_type, "later")

    def test_should_handle_regex_replacement_edge_cases(self):
        """Test edge cases in regex content replacement"""
        # Test content with multiple occurrences - replaces all
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="TODO: Review TODO items in the code",
            block_type="todo",
        )

        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        updated_block = command.execute()

        # Replaces all occurrences of TODO
        self.assertEqual(updated_block.content, "DOING: Review DOING items in the code")
        self.assertEqual(updated_block.block_type, "doing")

    def test_should_handle_content_with_special_characters(self):
        """Test content replacement with special characters"""
        test_cases = [
            "TODO: Fix bug #123 (critical)",
            "TODO: Update config.json & settings.py",
            "TODO: Test with 100% coverage",
            "TODO: Research @mentions functionality",
        ]

        for content in test_cases:
            with self.subTest(content=content):
                block = BlockFactory(
                    user=self.user, page=self.page, content=content, block_type="todo"
                )

                form_data = {"user": self.user.id, "block": str(block.uuid)}
                form = ToggleBlockTodoForm(form_data)
                form.is_valid()
                command = ToggleBlockTodoCommand(form)
                updated_block = command.execute()

                expected_content = content.replace("TODO", "DOING", 1)
                self.assertEqual(updated_block.content, expected_content)
                self.assertEqual(updated_block.block_type, "doing")

    def test_should_preserve_formatting_in_content(self):
        """Test that formatting and whitespace is preserved in content"""
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="TODO:   spaced    content   with    gaps",
            block_type="todo",
        )

        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        updated_block = command.execute()

        # Verify spacing is preserved
        self.assertEqual(
            updated_block.content, "DOING:   spaced    content   with    gaps"
        )
        self.assertEqual(updated_block.block_type, "doing")

    def test_later_and_wontdo_content_replacement(self):
        """Test content replacement for later and wontdo states"""
        # Test later -> wontdo
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="LATER review PR",
            block_type="later",
        )

        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command = ToggleBlockTodoCommand(form)
        updated_block = command.execute()

        self.assertEqual(updated_block.content, "WONTDO review PR")
        self.assertEqual(updated_block.block_type, "wontdo")

        # Test wontdo -> todo
        form_data = {"user": self.user.id, "block": str(block.uuid)}
        form = ToggleBlockTodoForm(form_data)
        form.is_valid()
        command2 = ToggleBlockTodoCommand(form)
        updated_block2 = command2.execute()

        self.assertEqual(updated_block2.content, "TODO review PR")
        self.assertEqual(updated_block2.block_type, "todo")
