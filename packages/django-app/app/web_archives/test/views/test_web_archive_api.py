from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import Asset
from core.test.helpers import UserFactory
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory


class WebArchiveAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_capture_endpoint_creates_pending_archive_row(self):
        block = BlockFactory(user=self.user, page=self.page)

        # Stub the background thread so nothing actually runs - we're only
        # asserting the sync half (pending row created, block flipped to
        # embed). Completion of the capture itself is covered by the
        # command-level tests which inject run_async=False.
        class NoopThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

        with patch(
            "web_archives.commands.capture_web_archive_command.threading.Thread",
            NoopThread,
        ):
            response = self.client.post(
                "/api/web-archives/capture/",
                {"block": str(block.uuid), "url": "https://example.com/a"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["source_url"], "https://example.com/a")
        self.assertEqual(response.data["data"]["status"], "pending")

        archive = WebArchive.objects.get(block=block)
        self.assertEqual(archive.status, "pending")
        self.assertEqual(archive.source_url, "https://example.com/a")

        block.refresh_from_db()
        self.assertEqual(block.content_type, "embed")
        self.assertEqual(block.media_url, "https://example.com/a")

    def test_capture_endpoint_rejects_block_owned_by_other_user(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user)
        other_block = BlockFactory(user=other_user, page=other_page)

        response = self.client.post(
            "/api/web-archives/capture/",
            {"block": str(other_block.uuid), "url": "https://example.com/a"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_capture_endpoint_requires_auth(self):
        self.client.credentials()
        block = BlockFactory(user=self.user, page=self.page)
        response = self.client.post(
            "/api/web-archives/capture/",
            {"block": str(block.uuid), "url": "https://example.com/a"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_web_archive_endpoint_returns_404_when_missing(self):
        block = BlockFactory(user=self.user, page=self.page)
        response = self.client.get(f"/api/web-archives/by-block/{block.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_web_archive_endpoint_returns_archive(self):
        block = BlockFactory(user=self.user, page=self.page)
        WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/a",
            status="ready",
            title="hello",
        )
        response = self.client.get(f"/api/web-archives/by-block/{block.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["title"], "hello")

    def test_readable_endpoint_streams_stored_html(self):
        block = BlockFactory(user=self.user, page=self.page)
        asset = Asset.objects.create(
            user=self.user,
            kind="web_archive_readable_html",
            source_url="https://example.com/a",
            mime_type="text/html; charset=utf-8",
        )
        asset.file.save("test.html", ContentFile(b"<p>hi</p>"), save=True)
        WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/a",
            status="ready",
            readable_asset=asset,
        )

        response = self.client.get(f"/api/web-archives/by-block/{block.uuid}/readable/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"<p>hi</p>")
        self.assertIn("text/html", response["Content-Type"])

    def test_readable_endpoint_404_when_no_archive(self):
        block = BlockFactory(user=self.user, page=self.page)
        response = self.client.get(f"/api/web-archives/by-block/{block.uuid}/readable/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_readable_endpoint_rejects_other_users_archive(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user)
        other_block = BlockFactory(user=other_user, page=other_page)
        asset = Asset.objects.create(
            user=other_user,
            kind="web_archive_readable_html",
            source_url="https://example.com/a",
        )
        asset.file.save("other.html", ContentFile(b"secret"), save=True)
        WebArchive.objects.create(
            user=other_user,
            block=other_block,
            source_url="https://example.com/a",
            status="ready",
            readable_asset=asset,
        )

        response = self.client.get(
            f"/api/web-archives/by-block/{other_block.uuid}/readable/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
