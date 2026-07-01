from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class GetPageWithBlocksReferencedChildrenTestCase(TestCase):
    """Referenced (linked) blocks should carry their nested children so a
    tag page can expand a tagged block and reveal its sub-blocks.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="owner@example.com")
        # The tag page the user navigates to (e.g. "mental health").
        cls.tag_page = PageFactory(
            user=cls.user, title="Mental Health", slug="mental-health"
        )
        # A note on another page tagged with the tag page, with children.
        cls.source_page = PageFactory(user=cls.user, title="Journal", slug="journal")
        cls.parent = BlockFactory(
            user=cls.user, page=cls.source_page, content="some note #mental-health"
        )
        cls.parent.pages.add(cls.tag_page)
        cls.child = BlockFactory(
            user=cls.user,
            page=cls.source_page,
            parent=cls.parent,
            content="a child detail",
            order=0,
        )

    def setUp(self):
        self.client = APIClient()
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_referenced_block_includes_children(self):
        response = self.client.get("/knowledge/api/page/?slug=mental-health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        referenced = response.data["data"]["referenced_blocks"]
        self.assertEqual(len(referenced), 1)

        ref_block = referenced[0]
        self.assertEqual(ref_block["uuid"], str(self.parent.uuid))
        self.assertIsNotNone(ref_block["children"])
        self.assertEqual(len(ref_block["children"]), 1)
        self.assertEqual(ref_block["children"][0]["uuid"], str(self.child.uuid))
        self.assertEqual(ref_block["children"][0]["content"], "a child detail")

    def test_child_tagged_alongside_ancestor_is_not_duplicated(self):
        # The child is ALSO tagged with the same page. It already shows up
        # nested under its tagged parent, so it must not appear again as its
        # own top-level reference entry.
        self.child.pages.add(self.tag_page)

        response = self.client.get("/knowledge/api/page/?slug=mental-health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        referenced = response.data["data"]["referenced_blocks"]
        top_level_uuids = [b["uuid"] for b in referenced]
        # Only the parent surfaces at top level; the child is deduped.
        self.assertEqual(top_level_uuids, [str(self.parent.uuid)])
        # ...but it's still reachable nested under the parent.
        self.assertEqual(referenced[0]["children"][0]["uuid"], str(self.child.uuid))

    def test_deeply_nested_tagged_descendant_is_deduped(self):
        # parent (tagged) -> child (untagged) -> grandchild (tagged).
        # The grandchild's ancestor is tagged, so it's deduped even though
        # the intermediate child isn't tagged.
        grandchild = BlockFactory(
            user=self.user,
            page=self.source_page,
            parent=self.child,
            content="a grandchild detail",
            order=0,
        )
        grandchild.pages.add(self.tag_page)

        response = self.client.get("/knowledge/api/page/?slug=mental-health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        referenced = response.data["data"]["referenced_blocks"]
        top_level_uuids = [b["uuid"] for b in referenced]
        self.assertEqual(top_level_uuids, [str(self.parent.uuid)])
