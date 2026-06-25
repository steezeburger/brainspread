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
