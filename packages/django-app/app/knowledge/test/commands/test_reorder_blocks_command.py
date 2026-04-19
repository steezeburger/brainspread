import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import ReorderBlocksCommand
from knowledge.forms import ReorderBlocksForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestReorderBlocksCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)
        cls.block_a = BlockFactory(user=cls.user, page=cls.page, order=0)
        cls.block_b = BlockFactory(user=cls.user, page=cls.page, order=1)
        cls.block_c = BlockFactory(user=cls.user, page=cls.page, order=2)

    def _execute(self, blocks_data):
        form = ReorderBlocksForm({"user": self.user.id, "blocks": blocks_data})
        form.is_valid()
        return ReorderBlocksCommand(form).execute()

    def test_reorders_blocks(self):
        self._execute(
            [
                {"uuid": str(self.block_a.uuid), "order": 2},
                {"uuid": str(self.block_b.uuid), "order": 0},
                {"uuid": str(self.block_c.uuid), "order": 1},
            ]
        )

        self.block_a.refresh_from_db()
        self.block_b.refresh_from_db()
        self.block_c.refresh_from_db()

        self.assertEqual(self.block_a.order, 2)
        self.assertEqual(self.block_b.order, 0)
        self.assertEqual(self.block_c.order, 1)

    def test_raises_validation_error_for_another_users_block(self):
        other_user = UserFactory()
        other_block = BlockFactory(user=other_user, page=PageFactory(user=other_user))

        form = ReorderBlocksForm(
            {
                "user": self.user.id,
                "blocks": [{"uuid": str(other_block.uuid), "order": 0}],
            }
        )
        form.is_valid()

        with self.assertRaises(ValidationError):
            ReorderBlocksCommand(form).execute()

    def test_raises_validation_error_for_nonexistent_block(self):
        form = ReorderBlocksForm(
            {
                "user": self.user.id,
                "blocks": [{"uuid": str(uuid.uuid4()), "order": 0}],
            }
        )
        form.is_valid()

        with self.assertRaises(ValidationError):
            ReorderBlocksCommand(form).execute()

    def test_raises_for_invalid_form(self):
        form = ReorderBlocksForm({"user": self.user.id, "blocks": []})
        form.is_valid()

        with self.assertRaises(ValidationError):
            ReorderBlocksCommand(form).execute()
