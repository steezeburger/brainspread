import uuid

from django.test import TestCase

from knowledge.forms import ReorderBlocksForm

from ..helpers import UserFactory


class TestReorderBlocksForm(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _form(self, blocks):
        return ReorderBlocksForm({"user": self.user.id, "blocks": blocks})

    def test_valid_data(self):
        form = self._form(
            [
                {"uuid": str(uuid.uuid4()), "order": 0},
                {"uuid": str(uuid.uuid4()), "order": 1},
            ]
        )
        self.assertTrue(form.is_valid())

    def test_invalid_when_blocks_is_empty_list(self):
        form = self._form([])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_blocks_is_not_a_list(self):
        form = self._form("not-a-list")
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_uuid_missing(self):
        form = self._form([{"order": 0}])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_order_missing(self):
        form = self._form([{"uuid": str(uuid.uuid4())}])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_uuid_malformed(self):
        form = self._form([{"uuid": "not-a-uuid", "order": 0}])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_order_is_negative(self):
        form = self._form([{"uuid": str(uuid.uuid4()), "order": -1}])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)

    def test_invalid_when_order_is_not_integer(self):
        form = self._form([{"uuid": str(uuid.uuid4()), "order": "first"}])
        self.assertFalse(form.is_valid())
        self.assertIn("blocks", form.errors)
