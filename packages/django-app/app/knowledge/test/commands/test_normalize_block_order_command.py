from django.test import TestCase

from knowledge.commands import NormalizeBlockOrderCommand
from knowledge.forms import NormalizeBlockOrderForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestNormalizeBlockOrderCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _run(self, page):
        form = NormalizeBlockOrderForm({"user": self.user.id, "page": str(page.uuid)})
        self.assertTrue(form.is_valid(), form.errors)
        return NormalizeBlockOrderCommand(form).execute()

    def test_renumbers_duplicates_and_gaps_per_sibling_group(self):
        a = BlockFactory(user=self.user, page=self.page, content="a", order=4)
        b = BlockFactory(user=self.user, page=self.page, content="b", order=4)
        c = BlockFactory(user=self.user, page=self.page, content="c", order=9)
        child1 = BlockFactory(
            user=self.user, page=self.page, parent=a, content="a1", order=7
        )
        child2 = BlockFactory(
            user=self.user, page=self.page, parent=a, content="a2", order=7
        )

        result = self._run(self.page)

        for block in (a, b, c, child1, child2):
            block.refresh_from_db()
        # Roots: dup 4s break by creation order, gap at 9 closes.
        self.assertEqual([a.order, b.order, c.order], [0, 1, 2])
        # Children renumber within their own group, independently.
        self.assertEqual([child1.order, child2.order], [0, 1])
        self.assertEqual(result["renumbered"], 5)

    def test_idempotent_second_run_touches_nothing(self):
        BlockFactory(user=self.user, page=self.page, content="x", order=3)
        BlockFactory(user=self.user, page=self.page, content="y", order=3)

        first = self._run(self.page)
        second = self._run(self.page)

        self.assertGreater(first["renumbered"], 0)
        self.assertEqual(second["renumbered"], 0)

    def test_rejects_other_users_page(self):
        other = UserFactory()
        their_page = PageFactory(user=other)
        form = NormalizeBlockOrderForm(
            {"user": self.user.id, "page": str(their_page.uuid)}
        )
        self.assertFalse(form.is_valid())
