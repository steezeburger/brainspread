from django.test import Client, TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class SharePageAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="owner@example.com")
        cls.page = PageFactory(user=cls.user, title="Roadmap", page_type="page")

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_share_endpoint_requires_authentication(self):
        self.client.credentials()
        response = self.client.post(
            "/knowledge/api/pages/share/",
            {"page": str(self.page.uuid), "share_mode": "link"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_share_endpoint_sets_link_mode_and_returns_token(self):
        response = self.client.post(
            "/knowledge/api/pages/share/",
            {"page": str(self.page.uuid), "share_mode": "link"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["share_mode"], "link")
        self.assertTrue(response.data["data"]["share_token"])

        self.page.refresh_from_db()
        self.assertEqual(self.page.share_mode, "link")
        self.assertTrue(self.page.is_publicly_viewable)

    def test_share_endpoint_rejects_other_users_page(self):
        outsider = UserFactory(email="outsider@example.com")
        outsider_token = Token.objects.create(user=outsider)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {outsider_token.key}")

        response = self.client.post(
            "/knowledge/api/pages/share/",
            {"page": str(self.page.uuid), "share_mode": "link"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

        self.page.refresh_from_db()
        self.assertEqual(self.page.share_mode, "private")


class PublicPageViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="author@example.com")
        cls.page = PageFactory(user=cls.user, title="Public Roadmap", page_type="page")
        BlockFactory(user=cls.user, page=cls.page, content="hello world", order=0)

    def test_public_view_404s_when_token_missing(self):
        client = Client()
        response = client.get("/knowledge/share/does-not-exist/")
        self.assertEqual(response.status_code, 404)

    def test_public_view_404s_when_page_is_private(self):
        # Token may exist (e.g. previously shared then revoked) but the
        # current mode is private, so the URL must stop resolving.
        self.page.share_token = "previously-shared-token"
        self.page.share_mode = "private"
        self.page.save()

        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")
        self.assertEqual(response.status_code, 404)

    def test_public_view_renders_when_shared_via_link(self):
        self.page.share_token = "link-mode-token"
        self.page.share_mode = "link"
        self.page.save()

        client = Client()  # explicitly anonymous
        response = client.get(f"/knowledge/share/{self.page.share_token}/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Public Roadmap", body)
        self.assertIn("hello world", body)
        # Link mode should be marked noindex so it's not crawled
        self.assertIn("noindex", body)

    def test_public_view_marks_public_pages_as_indexable(self):
        self.page.share_token = "public-mode-token"
        self.page.share_mode = "public"
        self.page.save()

        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("index, follow", body)
