from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.test.helpers import UserFactory
from knowledge.models import Snapshot

from ..helpers import BlockFactory, PageFactory


class SnapshotAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_capture_endpoint_creates_pending_snapshot_row(self):
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
            "knowledge.commands.capture_url_snapshot_command.threading.Thread",
            NoopThread,
        ):
            response = self.client.post(
                "/knowledge/api/snapshots/capture/",
                {"block": str(block.uuid), "url": "https://example.com/a"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["source_url"], "https://example.com/a")
        self.assertEqual(response.data["data"]["status"], "pending")

        snapshot = Snapshot.objects.get(block=block)
        self.assertEqual(snapshot.status, "pending")
        self.assertEqual(snapshot.source_url, "https://example.com/a")

        block.refresh_from_db()
        self.assertEqual(block.content_type, "embed")
        self.assertEqual(block.media_url, "https://example.com/a")

    def test_capture_endpoint_rejects_block_owned_by_other_user(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user)
        other_block = BlockFactory(user=other_user, page=other_page)

        response = self.client.post(
            "/knowledge/api/snapshots/capture/",
            {"block": str(other_block.uuid), "url": "https://example.com/a"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_capture_endpoint_requires_auth(self):
        self.client.credentials()
        block = BlockFactory(user=self.user, page=self.page)
        response = self.client.post(
            "/knowledge/api/snapshots/capture/",
            {"block": str(block.uuid), "url": "https://example.com/a"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_snapshot_endpoint_returns_404_when_missing(self):
        block = BlockFactory(user=self.user, page=self.page)
        response = self.client.get(f"/knowledge/api/snapshots/by-block/{block.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_snapshot_endpoint_returns_snapshot(self):
        block = BlockFactory(user=self.user, page=self.page)
        Snapshot.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/a",
            status="ready",
            title="hello",
        )
        response = self.client.get(f"/knowledge/api/snapshots/by-block/{block.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["title"], "hello")
