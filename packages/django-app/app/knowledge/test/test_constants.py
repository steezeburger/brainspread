"""Guards on the shared block_type sets (issue #205).

The point of hoisting these into one module is that a new todo kind is
one edit. That only holds if the sets stay honest about what the model
actually offers, so these tests fail loudly when the two drift - a
typo'd or stale member would otherwise surface as an empty saved view
or a QueryEngineError at seed time, well away from the cause.
"""

from django.test import SimpleTestCase

from knowledge.constants import COMPLETED_TODO_TYPES, OPEN_TODO_TYPES, TODO_TYPES
from knowledge.models import Block


def _model_block_types() -> set:
    return {choice[0] for choice in Block._meta.get_field("block_type").choices}


class BlockTypeConstantsTestCase(SimpleTestCase):
    def test_every_member_is_a_real_block_type(self):
        unknown = set(TODO_TYPES) - _model_block_types()
        self.assertEqual(unknown, set(), f"not valid block_type choices: {unknown}")

    def test_open_and_completed_do_not_overlap(self):
        self.assertEqual(set(OPEN_TODO_TYPES) & set(COMPLETED_TODO_TYPES), set())

    def test_todo_types_is_the_union(self):
        self.assertEqual(
            set(TODO_TYPES), set(OPEN_TODO_TYPES) | set(COMPLETED_TODO_TYPES)
        )

    def test_non_todo_block_types_are_excluded(self):
        # bullet / heading / quote / code / divider track no work, so a
        # todo set that swallowed one would hand "Mark done" to a heading.
        for block_type in ("bullet", "heading", "quote", "code", "divider"):
            self.assertNotIn(block_type, TODO_TYPES)

    def test_sets_are_immutable(self):
        # They are module-level and shared; a list would let one caller's
        # mutation leak into every other call site.
        for constant in (OPEN_TODO_TYPES, COMPLETED_TODO_TYPES, TODO_TYPES):
            self.assertIsInstance(constant, tuple)
