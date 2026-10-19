from importlib import import_module

from django.apps import apps
from django.test import TestCase

from knowledge.models import Block

from ..helpers import BlockFactory, PageFactory, UserFactory

backfill_prefixes = import_module(
    "knowledge.migrations.0051_backfill_todo_state_prefixes"
).backfill_prefixes


class TestBackfillTodoStatePrefixes(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _block(self, content, block_type):
        return BlockFactory(
            user=self.user, page=self.page, content=content, block_type=block_type
        )

    def test_backfills_missing_and_mismatched_prefixes(self):
        missing = self._block("put trash and recycling out tonight", "todo")
        mismatched = self._block("TODO: paid rent", "done")
        correct = self._block("later: maybe", "later")
        bullet = self._block("just a note", "bullet")
        empty = self._block("", "todo")

        backfill_prefixes(apps, None)

        contents = {
            b.id: b.content
            for b in Block.objects.filter(
                id__in=[missing.id, mismatched.id, correct.id, bullet.id, empty.id]
            )
        }
        self.assertEqual(
            contents[missing.id], "TODO put trash and recycling out tonight"
        )
        self.assertEqual(contents[mismatched.id], "DONE: paid rent")
        self.assertEqual(contents[correct.id], "later: maybe")
        self.assertEqual(contents[bullet.id], "just a note")
        self.assertEqual(contents[empty.id], "")
