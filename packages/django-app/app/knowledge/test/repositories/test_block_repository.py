from django.test import TestCase

from knowledge.repositories import BlockRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestGetReferencedBlocks(TestCase):
    """get_referenced_blocks returns blocks on other pages tagged with the
    given page, dropping descendants whose ancestor is also tagged (they
    already render nested under that ancestor)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.tag_page = PageFactory(user=cls.user, title="Tag", slug="tag")
        cls.source = PageFactory(user=cls.user, title="Source", slug="source")

    def test_returns_tagged_block_from_other_page(self):
        block = BlockFactory(user=self.user, page=self.source)
        block.pages.add(self.tag_page)

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual([b.id for b in result], [block.id])

    def test_excludes_blocks_belonging_to_the_tag_page_itself(self):
        own = BlockFactory(user=self.user, page=self.tag_page)
        own.pages.add(self.tag_page)

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual(result, [])

    def test_dedupes_child_when_ancestor_is_also_tagged(self):
        parent = BlockFactory(user=self.user, page=self.source)
        parent.pages.add(self.tag_page)
        child = BlockFactory(user=self.user, page=self.source, parent=parent)
        child.pages.add(self.tag_page)

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual([b.id for b in result], [parent.id])

    def test_dedupes_deeply_nested_descendant_through_untagged_ancestor(self):
        parent = BlockFactory(user=self.user, page=self.source)
        parent.pages.add(self.tag_page)
        # Intermediate block is NOT tagged.
        middle = BlockFactory(user=self.user, page=self.source, parent=parent)
        grandchild = BlockFactory(user=self.user, page=self.source, parent=middle)
        grandchild.pages.add(self.tag_page)

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual([b.id for b in result], [parent.id])

    def test_keeps_tagged_child_when_ancestor_not_tagged(self):
        # Parent isn't tagged, so the tagged child has no tagged ancestor and
        # must surface as its own top-level reference.
        parent = BlockFactory(user=self.user, page=self.source)
        child = BlockFactory(user=self.user, page=self.source, parent=parent)
        child.pages.add(self.tag_page)

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual([b.id for b in result], [child.id])

    def test_excludes_a_soft_deleted_tagged_block(self):
        block = BlockFactory(user=self.user, page=self.source)
        block.pages.add(self.tag_page)
        block.delete()

        result = BlockRepository.get_referenced_blocks(self.tag_page)
        self.assertEqual(result, [])


class TestSearchByContentExcludesDeleted(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_soft_deleted_blocks_drop_out_of_search(self):
        BlockFactory(user=self.user, page=self.page, content="find me please")
        gone = BlockFactory(
            user=self.user, page=self.page, content="find me too, but deleted"
        )
        gone.delete()

        results = list(BlockRepository.search_by_content(self.user, "find me"))

        self.assertEqual(len(results), 1)
        self.assertNotIn(gone.id, [b.id for b in results])


class TestSoftDeleteCascades(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_soft_delete_subtree_only_touches_active_descendants(self):
        root = BlockFactory(user=self.user, page=self.page)
        child = BlockFactory(user=self.user, page=self.page, parent=root)
        already_gone = BlockFactory(user=self.user, page=self.page, parent=root)
        already_gone.delete()
        other_deleted_at = already_gone.deleted_at

        BlockRepository.soft_delete_subtree(root)

        root.refresh_from_db()
        child.refresh_from_db()
        already_gone.refresh_from_db()
        self.assertFalse(root.is_active)
        self.assertFalse(child.is_active)
        # Untouched — keeps its original deleted_at rather than being
        # re-stamped by the cascade.
        self.assertEqual(already_gone.deleted_at, other_deleted_at)

    def test_restore_subtree_restores_the_whole_tree_regardless_of_state(self):
        root = BlockFactory(user=self.user, page=self.page)
        child = BlockFactory(user=self.user, page=self.page, parent=root)
        grandchild = BlockFactory(user=self.user, page=self.page, parent=child)
        BlockRepository.soft_delete_subtree(root)

        BlockRepository.restore_subtree(root)

        for b in (root, child, grandchild):
            b.refresh_from_db()
            self.assertTrue(b.is_active)
            self.assertIsNone(b.deleted_at)

    def test_soft_delete_and_restore_page_blocks(self):
        on_page = BlockFactory(user=self.user, page=self.page)
        other_page = PageFactory(user=self.user)
        elsewhere = BlockFactory(user=self.user, page=other_page)

        count = BlockRepository.soft_delete_page_blocks(self.page)
        self.assertEqual(count, 1)
        on_page.refresh_from_db()
        elsewhere.refresh_from_db()
        self.assertFalse(on_page.is_active)
        self.assertTrue(elsewhere.is_active)

        restored = BlockRepository.restore_page_blocks(self.page)
        self.assertEqual(restored, 1)
        on_page.refresh_from_db()
        self.assertTrue(on_page.is_active)

    def test_get_deleted_by_uuid_scoped_to_user(self):
        block = BlockFactory(user=self.user, page=self.page)
        block.delete()
        other = UserFactory()

        self.assertEqual(
            BlockRepository.get_deleted_by_uuid(str(block.uuid), self.user).id,
            block.id,
        )
        self.assertIsNone(BlockRepository.get_deleted_by_uuid(str(block.uuid), other))

    def test_get_purgeable_filters_by_cutoff(self):
        from datetime import timedelta

        from django.utils import timezone

        from knowledge.models import Block

        old = BlockFactory(user=self.user, page=self.page)
        old.delete()
        Block.objects.filter(pk=old.pk).update(
            deleted_at=timezone.now() - timedelta(days=45)
        )
        recent = BlockFactory(user=self.user, page=self.page)
        recent.delete()

        cutoff = timezone.now() - timedelta(days=30)
        purgeable_ids = list(
            BlockRepository.get_purgeable(cutoff).values_list("id", flat=True)
        )

        self.assertIn(old.id, purgeable_ids)
        self.assertNotIn(recent.id, purgeable_ids)
