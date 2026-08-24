from django.test import TestCase

from knowledge.commands import NormalizeBlockOrderCommand
from knowledge.forms import NormalizeBlockOrderForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestNormalizeBlockOrderCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _run(self, page, dry_run=False):
        form = NormalizeBlockOrderForm({"page": str(page.uuid), "dry_run": dry_run})
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

    def test_cross_page_orphans_are_left_untouched(self):
        # A block whose parent lives on ANOTHER page belongs to that
        # parent's sibling group — renumbering it here would collide
        # with the parent's real children (and jump the orphan from the
        # end of the child list to the front).
        other_page = PageFactory(user=self.user)
        parent_elsewhere = BlockFactory(
            user=self.user, page=other_page, content="p", order=0
        )
        orphan = BlockFactory(
            user=self.user,
            page=self.page,
            parent=parent_elsewhere,
            content="orphan",
            order=41,
        )
        BlockFactory(user=self.user, page=self.page, content="root", order=3)

        result = self._run(self.page)

        orphan.refresh_from_db()
        self.assertEqual(orphan.order, 41)
        self.assertEqual(result["skipped_orphans"], 1)

    def test_cross_page_children_renumber_with_their_group(self):
        # The renderer fetches child lists by parent with NO page
        # filter, so an on-page parent's group includes legacy children
        # living on other pages. The repair must renumber the FULL
        # rendered group — compacting only the on-page members could
        # land them on an order the cross-page child already holds.
        other_page = PageFactory(user=self.user)
        parent = BlockFactory(user=self.user, page=self.page, content="p", order=0)
        stray = BlockFactory(
            user=self.user, page=other_page, parent=parent, content="stray", order=0
        )
        local = BlockFactory(
            user=self.user, page=self.page, parent=parent, content="local", order=5
        )

        result = self._run(self.page)

        stray.refresh_from_db()
        local.refresh_from_db()
        # Group sorted by (order, created_at, id): stray keeps 0,
        # local compacts to 1 — no collision with the excluded row.
        self.assertEqual([stray.order, local.order], [0, 1])
        self.assertEqual(result["renumbered"], 1)

        # Repairing the stray's own page afterwards must not reshuffle:
        # there it's an orphan (parent lives elsewhere) and is skipped.
        other_result = self._run(other_page)
        stray.refresh_from_db()
        self.assertEqual(stray.order, 0)
        self.assertEqual(other_result["skipped_orphans"], 1)

    def test_dry_run_counts_without_persisting(self):
        a = BlockFactory(user=self.user, page=self.page, content="a", order=3)
        b = BlockFactory(user=self.user, page=self.page, content="b", order=3)

        result = self._run(self.page, dry_run=True)

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(result["renumbered"], 2)
        self.assertEqual([a.order, b.order], [3, 3])

    def test_repair_does_not_bump_modified_at(self):
        block = BlockFactory(user=self.user, page=self.page, content="m", order=7)
        before = block.modified_at

        self._run(self.page)

        block.refresh_from_db()
        self.assertEqual(block.order, 0)
        self.assertEqual(block.modified_at, before)
