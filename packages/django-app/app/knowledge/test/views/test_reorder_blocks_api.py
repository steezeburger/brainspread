from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class TestReorderBlocksAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)
        cls.block_a = BlockFactory(user=cls.user, page=cls.page, order=0)
        cls.block_b = BlockFactory(user=cls.user, page=cls.page, order=1)
        cls.block_c = BlockFactory(user=cls.user, page=cls.page, order=2)

    def setUp(self):
        self.client = APIClient()
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_reorders_blocks_successfully(self):
        response = self.client.put(
            "/knowledge/api/blocks/reorder/",
            {
                "blocks": [
                    {"uuid": str(self.block_a.uuid), "order": 2},
                    {"uuid": str(self.block_b.uuid), "order": 0},
                    {"uuid": str(self.block_c.uuid), "order": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        self.block_a.refresh_from_db()
        self.block_b.refresh_from_db()
        self.block_c.refresh_from_db()

        self.assertEqual(self.block_a.order, 2)
        self.assertEqual(self.block_b.order, 0)
        self.assertEqual(self.block_c.order, 1)

    def test_returns_400_for_empty_blocks(self):
        response = self.client.put(
            "/knowledge/api/blocks/reorder/",
            {"blocks": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_returns_400_for_invalid_uuid(self):
        response = self.client.put(
            "/knowledge/api/blocks/reorder/",
            {"blocks": [{"uuid": "not-a-uuid", "order": 0}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_returns_401_without_authentication(self):
        self.client.credentials()
        response = self.client.put(
            "/knowledge/api/blocks/reorder/",
            {"blocks": [{"uuid": str(self.block_a.uuid), "order": 0}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_reorder_another_users_blocks(self):
        other_user = UserFactory()
        other_block = BlockFactory(
            user=other_user, page=PageFactory(user=other_user), order=0
        )

        response = self.client.put(
            "/knowledge/api/blocks/reorder/",
            {"blocks": [{"uuid": str(other_block.uuid), "order": 5}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        other_block.refresh_from_db()
        self.assertEqual(other_block.order, 0)
