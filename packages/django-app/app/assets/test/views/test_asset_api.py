import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from assets.models import Asset
from core.test.helpers import UserFactory


class AssetAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    # --- upload --------------------------------------------------------

    def test_upload_requires_auth(self):
        self.client.credentials()
        upload = SimpleUploadedFile("a.png", b"fake", content_type="image/png")
        response = self.client.post(
            "/api/assets/", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_creates_asset_and_records_sha256(self):
        content = b"hello world"
        upload = SimpleUploadedFile("hello.txt", content, content_type="text/plain")

        response = self.client.post(
            "/api/assets/", {"file": upload}, format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])

        data = response.data["data"]
        self.assertEqual(data["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(data["byte_size"], len(content))
        self.assertEqual(data["mime_type"], "text/plain")
        self.assertEqual(
            data["file_type"], "other"
        )  # text/plain isn't in FILE_TYPE map
        self.assertEqual(data["asset_type"], Asset.ASSET_TYPE_UPLOAD)
        self.assertEqual(data["original_filename"], "hello.txt")

        asset = Asset.objects.get(uuid=data["uuid"])
        self.assertEqual(asset.user, self.user)
        self.assertEqual(asset.byte_size, len(content))

    def test_upload_dedupes_identical_bytes_for_same_user(self):
        content = b"dedupe-me"
        first = SimpleUploadedFile("a.txt", content, content_type="text/plain")
        second = SimpleUploadedFile("b.txt", content, content_type="text/plain")

        first_resp = self.client.post(
            "/api/assets/", {"file": first}, format="multipart"
        )
        second_resp = self.client.post(
            "/api/assets/", {"file": second}, format="multipart"
        )

        self.assertEqual(first_resp.status_code, 200)
        self.assertEqual(second_resp.status_code, 200)
        self.assertEqual(
            first_resp.data["data"]["uuid"],
            second_resp.data["data"]["uuid"],
            "Identical content should dedupe to the same Asset row",
        )
        self.assertEqual(Asset.objects.filter(user=self.user).count(), 1)

    def test_upload_does_not_dedupe_across_users(self):
        content = b"not-shared"

        # Same bytes, different user - must NOT collapse, otherwise the
        # second user could probe whether the first user owns the asset.
        first = SimpleUploadedFile("a.txt", content, content_type="text/plain")
        self.client.post("/api/assets/", {"file": first}, format="multipart")

        other_token = Token.objects.create(user=self.other_user)
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f"Token {other_token.key}")

        second = SimpleUploadedFile("b.txt", content, content_type="text/plain")
        other_resp = other_client.post(
            "/api/assets/", {"file": second}, format="multipart"
        )

        self.assertEqual(other_resp.status_code, 200)
        self.assertEqual(Asset.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Asset.objects.filter(user=self.other_user).count(), 1)

    @override_settings(ASSET_UPLOAD_MAX_BYTES=10)
    def test_upload_rejects_oversize(self):
        upload = SimpleUploadedFile("big.txt", b"x" * 11, content_type="text/plain")
        response = self.client.post(
            "/api/assets/", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data["errors"])

    def test_upload_rejects_mime_outside_whitelist(self):
        upload = SimpleUploadedFile(
            "evil.exe", b"MZ\x00\x00", content_type="application/x-msdownload"
        )
        response = self.client.post(
            "/api/assets/", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data["errors"])
        self.assertEqual(Asset.objects.count(), 0)

    def test_upload_assigns_image_file_type(self):
        upload = SimpleUploadedFile(
            "pic.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        response = self.client.post(
            "/api/assets/", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["file_type"], Asset.FILE_TYPE_IMAGE)

    def test_upload_honors_explicit_asset_type(self):
        upload = SimpleUploadedFile(
            "block.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        response = self.client.post(
            "/api/assets/",
            {"file": upload, "asset_type": Asset.ASSET_TYPE_BLOCK_ATTACHMENT},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["data"]["asset_type"], Asset.ASSET_TYPE_BLOCK_ATTACHMENT
        )

    # --- serve ---------------------------------------------------------

    def _create_asset(self, *, user, content: bytes, mime: str = "image/png") -> Asset:
        asset = Asset.objects.create(
            user=user,
            asset_type=Asset.ASSET_TYPE_UPLOAD,
            file_type=Asset.FILE_TYPE_IMAGE,
            mime_type=mime,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            original_filename="test.png",
        )
        asset.file.save(
            "test.png",
            SimpleUploadedFile("test.png", content, content_type=mime),
            save=True,
        )
        return asset

    def test_serve_requires_auth(self):
        self.client.credentials()
        asset = self._create_asset(user=self.user, content=b"abc")
        response = self.client.get(f"/api/assets/{asset.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_serve_returns_bytes_for_owner(self):
        asset = self._create_asset(user=self.user, content=b"owner-bytes")
        response = self.client.get(f"/api/assets/{asset.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"owner-bytes")
        self.assertIn("image/png", response["Content-Type"])
        self.assertIn("inline", response["Content-Disposition"])

    def test_serve_404s_for_other_users_asset(self):
        # Belongs to a different user - we must not leak its existence,
        # let alone its bytes.
        asset = self._create_asset(user=self.other_user, content=b"private")
        response = self.client.get(f"/api/assets/{asset.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_serve_404s_for_unknown_uuid(self):
        response = self.client.get("/api/assets/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_serve_returns_bytes_for_staff_user_owning_other_users_asset(self):
        # Admin / staff need to be able to preview any asset from the
        # Django admin without exposing /media/ publicly.
        staff_user = UserFactory(is_staff=True)
        staff_token = Token.objects.create(user=staff_user)
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Token {staff_token.key}")

        asset = self._create_asset(user=self.other_user, content=b"admin-can-see")
        response = staff_client.get(f"/api/assets/{asset.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"admin-can-see")

    def test_serve_404s_for_malformed_uuid(self):
        response = self.client.get("/api/assets/not-a-uuid/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
