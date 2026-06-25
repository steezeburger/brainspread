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
