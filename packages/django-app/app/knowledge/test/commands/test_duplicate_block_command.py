from django.test import TestCase
from django.utils import timezone

from knowledge.commands import DuplicateBlockCommand
from knowledge.forms import DuplicateBlockForm
from knowledge.models import Block, Page

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestDuplicateBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _duplicate(self, block):
        form = DuplicateBlockForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)
        return DuplicateBlockCommand(form).execute()

    def test_duplicates_a_root_block_directly_below_it(self):
        block = BlockFactory(user=self.user, page=self.page, content="hello", order=0)

        clone = self._duplicate(block)

        self.assertNotEqual(clone.uuid, block.uuid)
        self.assertEqual(clone.content, "hello")
        self.assertIsNone(clone.parent)
        self.assertEqual(clone.order, 1)

    def test_shifts_later_siblings_and_leaves_earlier_ones_alone(self):
        before = BlockFactory(user=self.user, page=self.page, order=0)
        block = BlockFactory(user=self.user, page=self.page, order=1)
        after = BlockFactory(user=self.user, page=self.page, order=2)

        self._duplicate(block)

        after.refresh_from_db()
        before.refresh_from_db()
        self.assertEqual(after.order, 3)
        self.assertEqual(before.order, 0)

    def test_duplicates_within_parent_scope_only(self):
        parent = BlockFactory(user=self.user, page=self.page, order=0)
        child = BlockFactory(user=self.user, page=self.page, parent=parent, order=0)
        sibling_child = BlockFactory(
            user=self.user, page=self.page, parent=parent, order=1
        )
        other_root = BlockFactory(user=self.user, page=self.page, order=5)

        clone = self._duplicate(child)

        self.assertEqual(clone.parent_id, parent.id)
        self.assertEqual(clone.order, 1)
        sibling_child.refresh_from_db()
        other_root.refresh_from_db()
        self.assertEqual(sibling_child.order, 2)
        # Root-level block is a different order scope; untouched.
        self.assertEqual(other_root.order, 5)

    def test_clones_descendant_subtree_preserving_structure(self):
        root = BlockFactory(user=self.user, page=self.page, content="root", order=0)
        child = BlockFactory(
            user=self.user, page=self.page, parent=root, content="child", order=0
        )
        grandchild = BlockFactory(
            user=self.user,
            page=self.page,
            parent=child,
            content="grandchild",
            order=0,
        )

        clone = self._duplicate(root)

        clone_children = list(Block.objects.filter(parent=clone))
        self.assertEqual(len(clone_children), 1)
        clone_child = clone_children[0]
        self.assertNotEqual(clone_child.uuid, child.uuid)
        self.assertEqual(clone_child.content, "child")
        self.assertEqual(clone_child.order, 0)

        clone_grandchildren = list(Block.objects.filter(parent=clone_child))
        self.assertEqual(len(clone_grandchildren), 1)
        self.assertEqual(clone_grandchildren[0].content, "grandchild")
        self.assertNotEqual(clone_grandchildren[0].uuid, grandchild.uuid)

    def test_clears_completed_at_on_the_clone(self):
        block = BlockFactory(
            user=self.user,
            page=self.page,
            block_type="done",
            completed_at=timezone.now(),
        )

        clone = self._duplicate(block)

        self.assertIsNone(clone.completed_at)

    def test_preserves_tags(self):
        tag_page = Page.objects.create(user=self.user, title="tag", slug="tag")
        block = BlockFactory(user=self.user, page=self.page)
        block.pages.set([tag_page])

        clone = self._duplicate(block)

        self.assertEqual(list(clone.pages.all()), [tag_page])

    def test_touches_the_page(self):
        block = BlockFactory(user=self.user, page=self.page)
        self.page.modified_at = timezone.now() - timezone.timedelta(days=1)
        self.page.save(update_fields=["modified_at"])
        stale_modified_at = self.page.modified_at

        self._duplicate(block)

        self.page.refresh_from_db()
        self.assertGreater(self.page.modified_at, stale_modified_at)
