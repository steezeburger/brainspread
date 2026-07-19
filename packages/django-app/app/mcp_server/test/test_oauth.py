import base64
import hashlib
import json
import secrets
from datetime import timedelta
from typing import Tuple
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.utils import timezone

from core.test.helpers import UserFactory
from mcp_server.models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient
from mcp_server.repositories import (
    OAuthAccessTokenRepository,
    OAuthAuthorizationCodeRepository,
    OAuthClientRepository,
)

REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def _pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _location_params(response) -> dict:
    query = urlsplit(response["Location"]).query
    return {key: values[0] for key, values in parse_qs(query).items()}


class OAuthTestCase(TestCase):
    """Shared fixtures: a user with a password and a registered client."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="oauth-user@example.com")
        cls.user.set_password("correct-horse")
        cls.user.save()
        cls.client_app = OAuthClientRepository.create(
            client_name="Claude", redirect_uris=[REDIRECT_URI]
        )

    def _authorize_params(self, challenge: str, **overrides) -> dict:
        params = {
            "client_id": self.client_app.client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "opaque-state",
        }
        params.update(overrides)
        return params

    def _approved_code(self, challenge: str) -> str:
        """Run the approve flow with a logged-in session, return the code."""
        self.client.force_login(self.user)
        response = self.client.post(
            "/oauth/authorize",
            {**self._authorize_params(challenge), "action": "approve"},
        )
        assert response.status_code == 302, response.content
        return _location_params(response)["code"]

    def _exchange(self, code: str, verifier: str, **overrides):
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_app.client_id,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
        payload.update(overrides)
        return self.client.post("/oauth/token", payload)


class MetadataEndpointsTest(OAuthTestCase):
    def test_authorization_server_metadata(self):
        response = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        issuer = body["issuer"]
        self.assertEqual(body["authorization_endpoint"], f"{issuer}/oauth/authorize")
        self.assertEqual(body["token_endpoint"], f"{issuer}/oauth/token")
        self.assertEqual(body["registration_endpoint"], f"{issuer}/oauth/register")
        self.assertEqual(body["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(body["token_endpoint_auth_methods_supported"], ["none"])
        self.assertIn("refresh_token", body["grant_types_supported"])

    def test_protected_resource_metadata(self):
        response = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["resource"].endswith("/api/mcp/"))
        self.assertEqual(len(body["authorization_servers"]), 1)

    def test_path_suffixed_discovery_variants(self):
        # Clients derive path-suffixed .well-known URLs from the
        # resource URL; both server and resource docs must resolve.
        for url in [
            "/.well-known/oauth-protected-resource/api/mcp",
            "/.well-known/oauth-protected-resource/api/mcp/",
            "/.well-known/oauth-authorization-server/api/mcp",
            "/.well-known/oauth-authorization-server/api/mcp/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class ClientRegistrationTest(TestCase):
    def test_register_client(self):
        response = self.client.post(
            "/oauth/register",
            data=json.dumps({"client_name": "Claude", "redirect_uris": [REDIRECT_URI]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["client_id"])
        self.assertEqual(body["redirect_uris"], [REDIRECT_URI])
        self.assertEqual(body["token_endpoint_auth_method"], "none")
        self.assertIsNotNone(OAuthClientRepository.get_by_client_id(body["client_id"]))

    def test_register_client_defaults_name(self):
        response = self.client.post(
            "/oauth/register",
            data=json.dumps({"redirect_uris": [REDIRECT_URI]}),
            content_type="application/json",
        )
        self.assertEqual(response.json()["client_name"], "MCP Client")

    def test_register_rejects_http_non_loopback_redirect(self):
        response = self.client.post(
            "/oauth/register",
            data=json.dumps({"redirect_uris": ["http://evil.example/cb"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_redirect_uri")

    def test_register_allows_loopback_http(self):
        response = self.client.post(
            "/oauth/register",
            data=json.dumps({"redirect_uris": ["http://127.0.0.1:33418/cb"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_register_rejects_malformed_json(self):
        response = self.client.post(
            "/oauth/register", data="not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class AuthorizeEndpointTest(OAuthTestCase):
    def test_unknown_client_renders_error_not_redirect(self):
        _, challenge = _pkce_pair()
        response = self.client.get(
            "/oauth/authorize",
            self._authorize_params(challenge, client_id="nope"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response)

    def test_unregistered_redirect_uri_rejected(self):
        _, challenge = _pkce_pair()
        response = self.client.get(
            "/oauth/authorize",
            self._authorize_params(challenge, redirect_uri="https://evil.example/cb"),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_pkce_rejected(self):
        params = self._authorize_params("challenge")
        del params["code_challenge"]
        response = self.client.get("/oauth/authorize", params)
        self.assertEqual(response.status_code, 400)

    def test_plain_pkce_method_rejected(self):
        _, challenge = _pkce_pair()
        response = self.client.get(
            "/oauth/authorize",
            self._authorize_params(challenge, code_challenge_method="plain"),
        )
        self.assertEqual(response.status_code, 400)

    def test_consent_page_with_session(self):
        _, challenge = _pkce_pair()
        self.client.force_login(self.user)
        response = self.client.get(
            "/oauth/authorize", self._authorize_params(challenge)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claude")
        self.assertContains(response, "oauth-user@example.com")
        self.assertNotContains(response, 'name="password"')

    def test_consent_page_without_session_asks_for_credentials(self):
        _, challenge = _pkce_pair()
        response = self.client.get(
            "/oauth/authorize", self._authorize_params(challenge)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="password"')

    def test_approve_with_session_redirects_with_code_and_state(self):
        _, challenge = _pkce_pair()
        self.client.force_login(self.user)
        response = self.client.post(
            "/oauth/authorize",
            {**self._authorize_params(challenge), "action": "approve"},
        )
        self.assertEqual(response.status_code, 302)
        params = _location_params(response)
        self.assertEqual(params["state"], "opaque-state")
        auth_code = OAuthAuthorizationCodeRepository.get_by_code(params["code"])
        self.assertEqual(auth_code.user, self.user)
        self.assertEqual(auth_code.code_challenge, challenge)

    def test_deny_redirects_with_access_denied(self):
        _, challenge = _pkce_pair()
        self.client.force_login(self.user)
        response = self.client.post(
            "/oauth/authorize",
            {**self._authorize_params(challenge), "action": "deny"},
        )
        self.assertEqual(response.status_code, 302)
        params = _location_params(response)
        self.assertEqual(params["error"], "access_denied")
        self.assertNotIn("code", params)

    def test_approve_with_inline_credentials(self):
        _, challenge = _pkce_pair()
        response = self.client.post(
            "/oauth/authorize",
            {
                **self._authorize_params(challenge),
                "action": "approve",
                "email": "oauth-user@example.com",
                "password": "correct-horse",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("code", _location_params(response))

    def test_approve_with_bad_credentials_rerenders_consent(self):
        _, challenge = _pkce_pair()
        response = self.client.post(
            "/oauth/authorize",
            {
                **self._authorize_params(challenge),
                "action": "approve",
                "email": "oauth-user@example.com",
                "password": "wrong",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "invalid email or password", status_code=401)
        self.assertEqual(OAuthAuthorizationCode.objects.count(), 0)


class TokenEndpointTest(OAuthTestCase):
    def test_full_exchange_and_mcp_call(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        response = self._exchange(code, verifier)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertGreater(body["expires_in"], 0)
        self.assertTrue(body["refresh_token"])

        # The issued bearer token must work against the MCP endpoint.
        mcp_response = self.client.post(
            "/api/mcp/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {body['access_token']}",
        )
        self.assertEqual(mcp_response.status_code, 200)
        tool_names = {t["name"] for t in mcp_response.json()["result"]["tools"]}
        self.assertIn("create_block", tool_names)

    def test_wrong_verifier_rejected(self):
        _, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        other_verifier, _ = _pkce_pair()
        response = self._exchange(code, other_verifier)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_code_is_single_use(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        self.assertEqual(self._exchange(code, verifier).status_code, 200)
        replay = self._exchange(code, verifier)
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()["error"], "invalid_grant")

    def test_expired_code_rejected(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        auth_code = OAuthAuthorizationCodeRepository.get_by_code(code)
        auth_code.expires_at = timezone.now() - timedelta(seconds=1)
        auth_code.save(update_fields=["expires_at"])
        response = self._exchange(code, verifier)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_redirect_uri_mismatch_rejected(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        response = self._exchange(
            code, verifier, redirect_uri="https://claude.ai/other"
        )
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_client_id_mismatch_rejected(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        other = OAuthClientRepository.create(
            client_name="Other", redirect_uris=[REDIRECT_URI]
        )
        response = self._exchange(code, verifier, client_id=other.client_id)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_client")

    def test_unsupported_grant_type(self):
        response = self.client.post(
            "/oauth/token", {"grant_type": "client_credentials"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_grant_type")

    def test_missing_fields_is_invalid_request(self):
        response = self.client.post(
            "/oauth/token", {"grant_type": "authorization_code"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_json_body_accepted(self):
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        response = self.client.post(
            "/oauth/token",
            data=json.dumps(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_app.client_id,
                    "redirect_uri": REDIRECT_URI,
                    "code_verifier": verifier,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)


class RefreshTokenTest(OAuthTestCase):
    def _issued_tokens(self) -> dict:
        verifier, challenge = _pkce_pair()
        code = self._approved_code(challenge)
        return self._exchange(code, verifier).json()

    def test_refresh_rotates_tokens(self):
        issued = self._issued_tokens()
        response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": self.client_app.client_id,
            },
        )
        self.assertEqual(response.status_code, 200)
        rotated = response.json()
        self.assertNotEqual(rotated["access_token"], issued["access_token"])
        self.assertNotEqual(rotated["refresh_token"], issued["refresh_token"])

        # The old pair is revoked: neither the old access token nor the
        # old refresh token works anymore.
        self.assertIsNone(
            OAuthAccessTokenRepository.get_active_by_access_token(
                issued["access_token"]
            )
        )
        replay = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": self.client_app.client_id,
            },
        )
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()["error"], "invalid_grant")

    def test_refresh_with_wrong_client_rejected(self):
        issued = self._issued_tokens()
        other = OAuthClientRepository.create(
            client_name="Other", redirect_uris=[REDIRECT_URI]
        )
        response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": other.client_id,
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_client")


class BearerAuthOnMCPEndpointTest(OAuthTestCase):
    def _mcp_post(self, auth_header: str = ""):
        kwargs = {}
        if auth_header:
            kwargs["HTTP_AUTHORIZATION"] = auth_header
        return self.client.post(
            "/api/mcp/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            content_type="application/json",
            **kwargs,
        )

    def test_unauthenticated_challenge_advertises_resource_metadata(self):
        response = self._mcp_post()
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata="', response.headers["WWW-Authenticate"])
        self.assertIn(
            "/.well-known/oauth-protected-resource",
            response.headers["WWW-Authenticate"],
        )

    def test_garbage_bearer_token_rejected(self):
        response = self._mcp_post("Bearer not-a-real-token")
        self.assertEqual(response.status_code, 401)

    def test_expired_access_token_rejected(self):
        token = OAuthAccessTokenRepository.create_for_user(
            client=self.client_app, user=self.user
        )
        OAuthAccessToken.objects.filter(pk=token.pk).update(
            access_expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = self._mcp_post(f"Bearer {token.access_token}")
        self.assertEqual(response.status_code, 401)

    def test_valid_bearer_token_pings(self):
        token = OAuthAccessTokenRepository.create_for_user(
            client=self.client_app, user=self.user
        )
        response = self._mcp_post(f"Bearer {token.access_token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], {})

    def test_bearer_token_scopes_tools_to_owning_user(self):
        other_user = UserFactory(email="other@example.com")
        token = OAuthAccessTokenRepository.create_for_user(
            client=self.client_app, user=other_user
        )
        response = self.client.post(
            "/api/mcp/",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "get_current_time", "arguments": {}},
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.access_token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"]["isError"])


class OAuthClientModelTest(TestCase):
    def test_registered_redirect_uri_check(self):
        client = OAuthClient(redirect_uris=[REDIRECT_URI])
        self.assertTrue(client.is_registered_redirect_uri(REDIRECT_URI))
        self.assertFalse(client.is_registered_redirect_uri("https://evil.example"))
