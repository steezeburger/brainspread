from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from assets.models import Asset
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
        # Shared pages must always be marked noindex — they're meant for a
        # specific recipient, not for search engines.
        self.assertIn("noindex", body)

    def test_public_view_includes_linked_references(self):
        # Topic / tag-style pages live on tagged blocks scattered across
        # daily notes. Sharing the topic page should surface those
        # references — without them a #food-log share would be empty.
        from datetime import date

        self.page.share_token = "tag-share-token"
        self.page.share_mode = "link"
        self.page.save()

        daily = PageFactory(
            user=self.user,
            title="2026-04-30",
            slug="2026-04-30",
            page_type="daily",
            date=date(2026, 4, 30),
        )
        tagged_block = BlockFactory(
            user=self.user,
            page=daily,
            content="ate spaghetti #food-log",
            order=0,
        )
        tagged_block.pages.add(self.page)

        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("ate spaghetti", body)
        self.assertIn("linked references", body)
        # Source-page label uses the daily's date, not its raw title.
        self.assertIn("2026-04-30", body)

    def test_public_view_excludes_blocks_tagged_with_other_pages(self):
        # A block tagged only with a different page must not leak just
        # because both pages belong to the same user.
        self.page.share_token = "scope-token"
        self.page.share_mode = "link"
        self.page.save()

        unrelated_topic = PageFactory(
            user=self.user, title="Other Topic", slug="other-topic"
        )
        other_block = BlockFactory(
            user=self.user,
            page=PageFactory(user=self.user, title="diary", slug="diary"),
            content="secret diary entry",
            order=0,
        )
        other_block.pages.add(unrelated_topic)

        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("secret diary entry", body)


class PublicAssetViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(email="owner@example.com")
        cls.outsider = UserFactory(email="outsider@example.com")

        cls.page = PageFactory(user=cls.owner, title="With Pictures")
        cls.page.share_token = "asset-share-token"
        cls.page.share_mode = "link"
        cls.page.save()

        # Asset attached via FK on a block in the shared page.
        cls.fk_asset = Asset.objects.create(
            user=cls.owner,
            file_type=Asset.FILE_TYPE_IMAGE,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file=SimpleUploadedFile(
                "fk.png", b"fake-fk-bytes", content_type="image/png"
            ),
            original_filename="fk.png",
            mime_type="image/png",
            byte_size=len(b"fake-fk-bytes"),
        )
        BlockFactory(
            user=cls.owner, page=cls.page, content="caption", asset=cls.fk_asset
        )

        # Asset embedded only via /api/assets/<uuid>/ in markdown content,
        # without an FK. This path should still resolve.
        cls.inline_asset = Asset.objects.create(
            user=cls.owner,
            file_type=Asset.FILE_TYPE_IMAGE,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file=SimpleUploadedFile(
                "inline.png", b"fake-inline-bytes", content_type="image/png"
            ),
            original_filename="inline.png",
            mime_type="image/png",
            byte_size=len(b"fake-inline-bytes"),
        )
        BlockFactory(
            user=cls.owner,
            page=cls.page,
            content=f"![](/api/assets/{cls.inline_asset.uuid}/)",
        )

        # Asset owned by the same user but NOT referenced by the shared
        # page — must remain private.
        cls.unrelated_asset = Asset.objects.create(
            user=cls.owner,
            file_type=Asset.FILE_TYPE_IMAGE,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file=SimpleUploadedFile(
                "secret.png", b"shouldnt-leak", content_type="image/png"
            ),
            original_filename="secret.png",
            mime_type="image/png",
            byte_size=len(b"shouldnt-leak"),
        )
        cls.private_page = PageFactory(user=cls.owner, title="Secret")
        BlockFactory(
            user=cls.owner,
            page=cls.private_page,
            content="confidential",
            asset=cls.unrelated_asset,
        )

    def test_serves_asset_referenced_via_fk(self):
        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}" f"/asset/{self.fk_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, b"fake-fk-bytes")

    def test_serves_asset_referenced_in_markdown_content(self):
        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}"
            f"/asset/{self.inline_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-inline-bytes")

    def test_serves_asset_attached_to_a_tagged_block(self):
        # An image on a daily-note block tagged with the shared page must
        # load — otherwise sharing a topic page with image references is
        # broken.
        tagged_asset = Asset.objects.create(
            user=self.owner,
            file_type=Asset.FILE_TYPE_IMAGE,
            asset_type=Asset.ASSET_TYPE_BLOCK_ATTACHMENT,
            file=SimpleUploadedFile(
                "tagged.png", b"tagged-bytes", content_type="image/png"
            ),
            original_filename="tagged.png",
            mime_type="image/png",
            byte_size=len(b"tagged-bytes"),
        )
        daily = PageFactory(
            user=self.owner,
            title="2026-04-29",
            slug="2026-04-29",
            page_type="daily",
        )
        tagged_block = BlockFactory(
            user=self.owner,
            page=daily,
            content="dinner",
            asset=tagged_asset,
            order=0,
        )
        tagged_block.pages.add(self.page)

        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}/asset/{tagged_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"tagged-bytes")

    def test_404s_for_unrelated_asset_even_when_owned_by_same_user(self):
        # Same user owns this asset, but it's only referenced by a private
        # page — sharing one page must not leak unrelated uploads.
        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}"
            f"/asset/{self.unrelated_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_404s_when_share_is_revoked(self):
        self.page.share_mode = "private"
        self.page.save()
        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}" f"/asset/{self.fk_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_404s_when_token_unknown(self):
        client = Client()
        response = client.get(
            f"/knowledge/share/never-issued/asset/{self.fk_asset.uuid}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_public_page_rewrites_inline_asset_urls(self):
        # The page render should swap /api/assets/<uuid>/ for the
        # token-scoped path so inline image markdown loads anonymously.
        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn(
            f"/knowledge/share/{self.page.share_token}"
            f"/asset/{self.inline_asset.uuid}/",
            body,
        )
        self.assertNotIn(f"/api/assets/{self.inline_asset.uuid}/", body)

    def test_public_page_renders_asset_image_tag_for_fk_attachments(self):
        client = Client()
        response = client.get(f"/knowledge/share/{self.page.share_token}/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn(
            f"/knowledge/share/{self.page.share_token}" f"/asset/{self.fk_asset.uuid}/",
            body,
        )

    def test_404s_for_invalid_uuid_format(self):
        # Even without a valid UUID, the view must 404 (not 500).
        client = Client()
        response = client.get(
            f"/knowledge/share/{self.page.share_token}/asset/not-a-uuid/"
        )
        self.assertEqual(response.status_code, 404)
