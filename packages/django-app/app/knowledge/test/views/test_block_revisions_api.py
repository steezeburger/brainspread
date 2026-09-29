from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.models import BlockRevision
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class BlockRevisionsAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="revisions@example.com")
        cls.page = PageFactory(user=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_list_revisions_newest_first(self):
        block = BlockFactory(user=self.user, page=self.page, content="v3")
        BlockRevision.objects.create(block=block, content="v1", block_type="bullet")
        BlockRevision.objects.create(block=block, content="v2", block_type="bullet")

        response = self.client.get(
            "/knowledge/api/blocks/revisions/", {"block": str(block.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual([r["content"] for r in response.data["data"]], ["v2", "v1"])

    def test_list_revisions_requires_authentication(self):
        self.client.credentials()
        block = BlockFactory(user=self.user, page=self.page, content="x")

        response = self.client.get(
            "/knowledge/api/blocks/revisions/", {"block": str(block.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_revisions_rejects_other_users_block(self):
        other = UserFactory(email="other@example.com")
        other_page = PageFactory(user=other)
        block = BlockFactory(user=other, page=other_page, content="x")

        response = self.client.get(
            "/knowledge/api/blocks/revisions/", {"block": str(block.uuid)}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_restore_revision_writes_values_and_appends_history(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="cleared", block_type="bullet"
        )
        revision = BlockRevision.objects.create(
            block=block, content="buy milk", block_type="bullet"
        )

        response = self.client.post(
            "/knowledge/api/blocks/revisions/restore/",
            {"block": str(block.uuid), "revision": str(revision.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["content"], "buy milk")
        self.assertEqual(block.revisions.count(), 2)

    def test_restore_revision_rejects_mismatched_block(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")
        other_block = BlockFactory(user=self.user, page=self.page, content="y")
        other_revision = BlockRevision.objects.create(
            block=other_block, content="z", block_type="bullet"
        )

        response = self.client.post(
            "/knowledge/api/blocks/revisions/restore/",
            {"block": str(block.uuid), "revision": str(other_revision.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
