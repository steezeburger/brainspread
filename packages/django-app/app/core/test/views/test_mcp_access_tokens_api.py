from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.test.helpers import McpAccessTokenFactory, UserFactory


def _initialize() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize"}


class McpAccessTokensAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def setUp(self):
        self.client = APIClient()
        self.web_token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.web_token.key}")

    def test_create_returns_key_once_and_list_never_does(self):
        response = self.client.post(
            "/api/auth/mcp-tokens/create/", {"name": "laptop"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        key = response.data["data"]["key"]
        self.assertTrue(key.startswith("bsmcp_"))

        response = self.client.get("/api/auth/mcp-tokens/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tokens = response.data["data"]["tokens"]
        self.assertEqual([t["name"] for t in tokens], ["laptop"])
        self.assertNotIn(key, str(response.content))

    def test_create_validates_input(self):
        response = self.client.post(
            "/api/auth/mcp-tokens/create/",
            {"name": "x", "expires_in_days": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_in_days", response.data["errors"])

    def test_revoke_unknown_token_is_404(self):
        other = McpAccessTokenFactory()
        response = self.client.post(
            "/api/auth/mcp-tokens/revoke/",
            {"token_uuid": str(other.uuid)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mcp_token_cannot_manage_tokens(self):
        """An MCP key only opens the MCP endpoint, so a leaked one can't
        mint more keys or reach the rest of the API."""
        raw_key = "bsmcp_scoped"
        McpAccessTokenFactory(user=self.user, raw_key=raw_key)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        response = self.client.post(
            "/api/auth/mcp-tokens/create/", {"name": "sneaky"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class McpEndpointAccessTokenAuthTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def setUp(self):
        self.client = APIClient()
        self.raw_key = "bsmcp_test-key"
        self.token = McpAccessTokenFactory(user=self.user, raw_key=self.raw_key)

    def _post(self, header: str):
        self.client.credentials(HTTP_AUTHORIZATION=header)
        return self.client.post("/api/mcp/", _initialize(), format="json")

    def test_bearer_key_authenticates_and_records_use(self):
        response = self._post(f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_token_keyword_works_too(self):
        response = self._post(f"Token {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_key_survives_web_logout(self):
        web_token = Token.objects.create(user=self.user)
        web_client = APIClient()
        web_client.credentials(HTTP_AUTHORIZATION=f"Token {web_token.key}")
        self.assertEqual(
            web_client.post("/api/auth/logout/").status_code, status.HTTP_200_OK
        )

        response = self._post(f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_legacy_web_token_still_works(self):
        web_token = Token.objects.create(user=self.user)
        response = self._post(f"Token {web_token.key}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_revoked_key_is_rejected(self):
        self.token.revoked_at = timezone.now()
        self.token.save()
        response = self._post(f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Bearer", response["WWW-Authenticate"])

    def test_expired_key_is_rejected(self):
        self.token.expires_at = timezone.now() - timedelta(seconds=1)
        self.token.save()
        response = self._post(f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_user_is_rejected(self):
        self.user.is_active = False
        self.user.save()
        response = self._post(f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_key_is_rejected(self):
        response = self._post("Bearer bsmcp_nope")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
