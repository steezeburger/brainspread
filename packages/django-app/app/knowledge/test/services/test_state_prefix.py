from django.test import SimpleTestCase

from knowledge.services.state_prefix import (
    ensure_state_prefix,
    has_state_marker,
    keeps_state_type,
)


class TestEnsureStatePrefix(SimpleTestCase):
    def test_prepends_missing_prefix(self):
        self.assertEqual(ensure_state_prefix("buy milk", "todo"), "TODO buy milk")

    def test_keeps_matching_prefix_any_case(self):
        self.assertEqual(
            ensure_state_prefix("todo: buy milk", "todo"), "todo: buy milk"
        )

    def test_swaps_other_keyword_in_place(self):
        self.assertEqual(
            ensure_state_prefix("TODO: buy milk", "done"), "DONE: buy milk"
        )

    def test_word_that_starts_with_keyword_is_not_a_prefix(self):
        self.assertEqual(
            ensure_state_prefix("Today I ship", "todo"), "TODO Today I ship"
        )

    def test_leaves_non_state_types_and_empty_content(self):
        self.assertEqual(ensure_state_prefix("buy milk", "bullet"), "buy milk")
        self.assertEqual(ensure_state_prefix("", "todo"), "")


class TestKeepsStateType(SimpleTestCase):
    def test_prefixless_content_on_todo_keeps_type(self):
        self.assertTrue(keeps_state_type("todo", "run the thing"))

    def test_content_naming_a_state_lets_auto_detect_run(self):
        self.assertFalse(keeps_state_type("todo", "DONE run the thing"))
        self.assertFalse(keeps_state_type("todo", "[x] run the thing"))

    def test_non_state_block_or_missing_content(self):
        self.assertFalse(keeps_state_type("bullet", "x"))
        self.assertFalse(keeps_state_type("todo", None))

    def test_has_state_marker(self):
        self.assertTrue(has_state_marker("  later: x"))
        self.assertFalse(has_state_marker("laterally"))
