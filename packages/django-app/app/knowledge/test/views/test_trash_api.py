from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.models import Block, Page
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class DeletePageAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="owner@example.com")

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_delete_page_soft_deletes_rather_than_removing_the_row(self):
        page = PageFactory(user=self.user)

        response = self.client.delete(
            "/knowledge/api/pages/delete/",
            {"page": str(page.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertTrue(Page.objects.filter(uuid=page.uuid).exists())
        page.refresh_from_db()
        self.assertFalse(page.is_active)

        # And it's gone from the normal listing.
        list_response = self.client.get("/knowledge/api/pages/list/")
        slugs = [p["slug"] for p in list_response.data["data"]["pages"]]
        self.assertNotIn(page.slug, slugs)


class TrashAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="owner@example.com")

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_get_trash_requires_authentication(self):
        self.client.credentials()
        response = self.client.get("/knowledge/api/trash/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_trash_lists_deleted_pages_and_blocks(self):
        page = PageFactory(user=self.user)
        page.delete()
        other_page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=other_page)
        block.delete()

        response = self.client.get("/knowledge/api/trash/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        page_uuids = [p["uuid"] for p in response.data["data"]["pages"]]
        block_uuids = [b["uuid"] for b in response.data["data"]["blocks"]]
        self.assertIn(str(page.uuid), page_uuids)
        self.assertIn(str(block.uuid), block_uuids)

    def test_restore_page_endpoint(self):
        page = PageFactory(user=self.user)
        page.delete()

        response = self.client.post(
            "/knowledge/api/trash/pages/restore/",
            {"page": str(page.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        page.refresh_from_db()
        self.assertTrue(page.is_active)

    def test_restore_page_rejects_another_users_page(self):
        other = UserFactory(email="outsider@example.com")
        page = PageFactory(user=other)
        page.delete()

        response = self.client.post(
            "/knowledge/api/trash/pages/restore/",
            {"page": str(page.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_restore_block_endpoint(self):
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        block.delete()

        response = self.client.post(
            "/knowledge/api/trash/blocks/restore/",
            {"block": str(block.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        block.refresh_from_db()
        self.assertTrue(block.is_active)

    def test_restore_block_restores_subtree(self):
        page = PageFactory(user=self.user)
        root = BlockFactory(user=self.user, page=page)
        child = BlockFactory(user=self.user, page=page, parent=root)
        root.delete()  # instance-level delete — no cascade on its own
        Block.objects.filter(pk=child.pk).update(is_active=False)

        response = self.client.post(
            "/knowledge/api/trash/blocks/restore/",
            {"block": str(root.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        root.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(root.is_active)
        self.assertTrue(child.is_active)
