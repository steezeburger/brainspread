"""Tests for the MCP OAuth 2.1 authorization-server glue.

Covers discovery metadata, the 401 ``WWW-Authenticate`` challenge,
dynamic client registration, and an end-to-end authorization-code +
PKCE flow that yields a token usable on ``/api/mcp/``.
"""

import base64
import hashlib
import json
import os
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from oauth2_provider.models import get_application_model

from core.test.helpers import UserFactory

Application = get_application_model()

REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _register(client, **overrides) -> dict:
    payload = {
        "client_name": "Claude",
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    payload.update(overrides)
    response = client.post(
        "/oauth/register",
        data=json.dumps(payload),
        content_type="application/json",
    )
    return response


class DiscoveryMetadataTests(TestCase):
    def test_authorization_server_metadata(self):
        body = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(body["issuer"], "http://testserver")
        self.assertEqual(
            body["authorization_endpoint"], "http://testserver/o/authorize/"
        )
        self.assertEqual(body["token_endpoint"], "http://testserver/o/token/")
        self.assertEqual(
            body["registration_endpoint"], "http://testserver/oauth/register"
        )
        self.assertEqual(body["code_challenge_methods_supported"], ["S256"])
        self.assertIn("authorization_code", body["grant_types_supported"])

    def test_protected_resource_metadata_root_and_pathed(self):
        for url in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/api/mcp",
        ):
            body = self.client.get(url).json()
            self.assertEqual(body["resource"], "http://testserver/api/mcp")
            self.assertEqual(body["authorization_servers"], ["http://testserver"])

    def test_metadata_sets_permissive_cors(self):
        response = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")


class UnauthenticatedChallengeTests(TestCase):
    def test_mcp_401_advertises_resource_metadata(self):
        response = self.client.post(
            "/api/mcp/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        challenge = response["WWW-Authenticate"]
        self.assertTrue(challenge.startswith("Bearer resource_metadata="))
        self.assertIn("/.well-known/oauth-protected-resource/api/mcp", challenge)

    def test_invalid_bearer_token_is_rejected(self):
        response = self.client.post(
            "/api/mcp/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        self.assertEqual(response.status_code, 401)


class DynamicClientRegistrationTests(TestCase):
    def test_registers_public_client(self):
        response = _register(self.client)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("client_id", body)
        self.assertNotIn("client_secret", body)
        self.assertEqual(body["token_endpoint_auth_method"], "none")
        self.assertEqual(body["redirect_uris"], [REDIRECT_URI])

        app = Application.objects.get(client_id=body["client_id"])
        self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)
        self.assertEqual(
            app.authorization_grant_type, Application.GRANT_AUTHORIZATION_CODE
        )
        self.assertFalse(app.skip_authorization)

    def test_confidential_client_gets_secret(self):
        response = _register(
            self.client, token_endpoint_auth_method="client_secret_post"
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("client_secret", body)
        self.assertEqual(body["token_endpoint_auth_method"], "client_secret_post")

    def test_missing_redirect_uris_is_rejected(self):
        response = _register(self.client, redirect_uris=[])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_disallowed_redirect_scheme_is_rejected(self):
        response = _register(self.client, redirect_uris=["ftp://evil.example/cb"])
        self.assertEqual(response.status_code, 400)

    def test_non_json_body_is_rejected(self):
        response = self.client.post(
            "/oauth/register", data="not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class AuthorizationCodeFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="oauth-user@example.com")

    def setUp(self):
        self.user.set_password("password")
        self.user.save()
        client_id = _register(self.client).json()["client_id"]
        self.client_id = client_id

    def _authorize_and_get_code(self, challenge: str) -> str:
        self.client.force_login(self.user)
        response = self.client.post(
            "/o/authorize/",
            data={
                "client_id": self.client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": "mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "allow": "Authorize",
            },
        )
        self.assertEqual(response.status_code, 302, getattr(response, "content", b""))
        location = response["Location"]
        self.assertTrue(location.startswith(REDIRECT_URI))
        code = parse_qs(urlparse(location).query)["code"][0]
        return code

    def test_full_flow_yields_token_that_authenticates_mcp(self):
        verifier, challenge = _pkce_pair()
        code = self._authorize_and_get_code(challenge)

        token_response = self.client.post(
            "/o/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": self.client_id,
                "code_verifier": verifier,
            },
        )
        self.assertEqual(token_response.status_code, 200, token_response.content)
        access_token = token_response.json()["access_token"]

        mcp_response = self.client.post(
            "/api/mcp/",
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(mcp_response.status_code, 200)
        self.assertEqual(
            mcp_response.json()["result"]["serverInfo"]["name"], "brainspread"
        )

    def test_token_rejects_wrong_pkce_verifier(self):
        _verifier, challenge = _pkce_pair()
        code = self._authorize_and_get_code(challenge)

        token_response = self.client.post(
            "/o/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": self.client_id,
                "code_verifier": "the-wrong-verifier-value-padded-to-length-here",
            },
        )
        self.assertEqual(token_response.status_code, 400)

    def test_authorize_requires_login(self):
        _verifier, challenge = _pkce_pair()
        response = self.client.get(
            "/o/authorize/",
            data={
                "client_id": self.client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": "mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/oauth/login/", response["Location"])
