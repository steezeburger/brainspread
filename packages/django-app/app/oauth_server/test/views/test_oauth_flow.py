from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.test.helpers import UserFactory
from oauth_server.models import OAuthAuthorizationCode, OAuthToken
from oauth_server.test.helpers import CLAUDE_CALLBACK, OAuthClientFactory, pkce_pair

SITE = "https://notes.example"


def _initialize() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize"}


@override_settings(SITE_URL=SITE)
class DiscoveryTests(TestCase):
    def test_unauthenticated_mcp_call_points_at_resource_metadata(self):
        response = self.client.post(
            "/api/mcp/", _initialize(), content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            f'Bearer resource_metadata="{SITE}/.well-known/oauth-protected-resource'
            '/api/mcp/", scope="mcp"',
        )

    def test_mcp_endpoint_answers_without_trailing_slash(self):
        response = self.client.post(
            "/api/mcp", _initialize(), content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn('oauth-protected-resource/api/mcp"', response["WWW-Authenticate"])

    def test_protected_resource_metadata_echoes_the_mcp_url(self):
        for path, resource in [
            ("/.well-known/oauth-protected-resource", f"{SITE}/api/mcp/"),
            ("/.well-known/oauth-protected-resource/api/mcp/", f"{SITE}/api/mcp/"),
            ("/.well-known/oauth-protected-resource/api/mcp", f"{SITE}/api/mcp"),
        ]:
            body = self.client.get(path).json()
            self.assertEqual(body["resource"], resource)
            self.assertEqual(body["authorization_servers"], [SITE])
        self.assertEqual(
            self.client.get("/.well-known/oauth-protected-resource/nope").status_code,
            404,
        )

    def test_authorization_server_metadata(self):
        body = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(body["issuer"], SITE)
        self.assertEqual(body["authorization_endpoint"], f"{SITE}/oauth/authorize/")
        self.assertEqual(body["token_endpoint"], f"{SITE}/oauth/token/")
        self.assertEqual(body["registration_endpoint"], f"{SITE}/oauth/register/")
        self.assertEqual(body["code_challenge_methods_supported"], ["S256"])
        self.assertIn("offline_access", body["scopes_supported"])
        self.assertEqual(body["token_endpoint_auth_methods_supported"], ["none"])


class RegistrationTests(TestCase):
    def test_registers_a_public_client(self):
        response = self.client.post(
            "/oauth/register/",
            {
                "client_name": "Claude",
                "redirect_uris": [CLAUDE_CALLBACK],
                "token_endpoint_auth_method": "client_secret_post",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["client_id"].startswith("bsc_"))
        self.assertEqual(body["token_endpoint_auth_method"], "none")
        self.assertNotIn("client_secret", body)

    def test_rejects_non_https_redirects(self):
        response = self.client.post(
            "/oauth/register/",
            {"redirect_uris": ["http://evil.example/cb"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_redirect_uri")

    def test_rejects_non_json(self):
        response = self.client.post(
            "/oauth/register/", "nope", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


@override_settings(SITE_URL=SITE)
class AuthorizationFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="me@example.com")
        cls.user.set_password("pw-12345!")
        cls.user.save()

    def setUp(self):
        self.oauth_client = OAuthClientFactory(client_name="Claude")
        self.verifier, self.challenge = pkce_pair()

    def _authorize_params(self, **overrides) -> dict:
        params = {
            "response_type": "code",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": CLAUDE_CALLBACK,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "mcp offline_access",
            "resource": f"{SITE}/api/mcp/",
        }
        params.update(overrides)
        return params

    def _approve(self, **overrides) -> dict:
        """Log in, allow, and return the redirect's query params."""
        self.client.force_login(self.user)
        response = self.client.post(
            "/oauth/authorize/",
            {**self._authorize_params(**overrides), "decision": "allow"},
        )
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(
            f"{location.scheme}://{location.netloc}{location.path}",
            overrides.get("redirect_uri", CLAUDE_CALLBACK),
        )
        return {k: v[0] for k, v in parse_qs(location.query).items()}

    def _exchange(self, code: str, **overrides):
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CLAUDE_CALLBACK,
            "client_id": self.oauth_client.client_id,
            "code_verifier": self.verifier,
        }
        data.update(overrides)
        return self.client.post("/oauth/token/", data)

    def _refresh(self, refresh_token: str):
        return self.client.post(
            "/oauth/token/",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.oauth_client.client_id,
            },
        )

    def _mcp(self, access_token: str):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        return api.post("/api/mcp/", _initialize(), format="json")

    # --- consent screen -------------------------------------------------

    def test_logged_out_user_is_sent_to_login_and_back(self):
        response = self.client.get("/oauth/authorize/", self._authorize_params())
        self.assertEqual(response.status_code, 302)
        login_url = response["Location"]
        self.assertTrue(login_url.startswith("/oauth/login/?next="))

        response = self.client.post(
            login_url, {"email": "me@example.com", "password": "pw-12345!"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/oauth/authorize/?"))

        response = self.client.get(response["Location"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connect Claude?")
        self.assertContains(response, "claude.ai")

    def test_wrong_password_stays_on_login(self):
        next_url = "/oauth/authorize/?client_id=x"
        response = self.client.post(
            "/oauth/login/",
            {"next": next_url, "email": "me@example.com", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrong email or password.")

    def test_login_refuses_to_redirect_off_the_authorize_page(self):
        for next_url in ["https://evil.example/", "//evil.example/", "/admin/"]:
            response = self.client.get("/oauth/login/", {"next": next_url})
            self.assertEqual(response.status_code, 400)

    def test_unknown_client_shows_error_page_instead_of_redirecting(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/oauth/authorize/", self._authorize_params(client_id="bsc_nope")
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "sign-in link", status_code=400)

    def test_unregistered_redirect_shows_error_page(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/oauth/authorize/",
            self._authorize_params(redirect_uri="https://evil.example/cb"),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_pkce_redirects_with_error(self):
        self.client.force_login(self.user)
        params = self._authorize_params()
        del params["code_challenge"]
        response = self.client.get("/oauth/authorize/", params)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["error"], ["invalid_request"])
        self.assertEqual(query["state"], ["xyz"])

    def test_deny_redirects_with_access_denied(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/oauth/authorize/", {**self._authorize_params(), "decision": "deny"}
        )
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["error"], ["access_denied"])
        self.assertEqual(query["state"], ["xyz"])

    def test_consent_post_requires_csrf(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            "/oauth/authorize/", {**self._authorize_params(), "decision": "allow"}
        )
        self.assertEqual(response.status_code, 403)

    # --- full flow ------------------------------------------------------

    def test_full_flow_with_rotation(self):
        query = self._approve()
        self.assertEqual(query["state"], "xyz")
        self.assertEqual(query["iss"], SITE)

        response = self._exchange(query["code"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        tokens = response.json()
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], 3600)
        self.assertEqual(self._mcp(tokens["access_token"]).status_code, 200)

        response = self._refresh(tokens["refresh_token"])
        self.assertEqual(response.status_code, 200, response.content)
        rotated = response.json()
        self.assertNotEqual(rotated["refresh_token"], tokens["refresh_token"])
        self.assertEqual(self._mcp(rotated["access_token"]).status_code, 200)
        # The rotated-out access token stops working.
        self.assertEqual(self._mcp(tokens["access_token"]).status_code, 401)

    def test_loopback_redirect_on_any_port(self):
        self.oauth_client.redirect_uris = ["http://localhost/callback"]
        self.oauth_client.save()
        redirect_uri = "http://localhost:3118/callback"
        query = self._approve(redirect_uri=redirect_uri)
        response = self._exchange(query["code"], redirect_uri=redirect_uri)
        self.assertEqual(response.status_code, 200, response.content)

    def test_wrong_pkce_verifier_is_rejected(self):
        query = self._approve()
        response = self._exchange(query["code"], code_verifier=pkce_pair()[0])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_mismatched_redirect_uri_is_rejected(self):
        self.oauth_client.redirect_uris = [CLAUDE_CALLBACK, "https://claude.ai/other"]
        self.oauth_client.save()
        query = self._approve()
        response = self._exchange(query["code"], redirect_uri="https://claude.ai/other")
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_code_for_another_client_is_rejected(self):
        query = self._approve()
        other = OAuthClientFactory()
        response = self._exchange(query["code"], client_id=other.client_id)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_replayed_code_revokes_what_it_minted(self):
        query = self._approve()
        tokens = self._exchange(query["code"]).json()

        response = self._exchange(query["code"])
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertEqual(self._mcp(tokens["access_token"]).status_code, 401)
        self.assertEqual(
            self._refresh(tokens["refresh_token"]).json()["error"], "invalid_grant"
        )

    def test_expired_code_is_rejected(self):
        query = self._approve()

        OAuthAuthorizationCode.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self._exchange(query["code"]).json()["error"], "invalid_grant")

    def test_refresh_reuse_after_grace_revokes_the_connection(self):
        tokens = self._exchange(self._approve()["code"]).json()
        rotated = self._refresh(tokens["refresh_token"]).json()
        OAuthToken.objects.filter(replaced_at__isnull=False).update(
            replaced_at=timezone.now() - timedelta(minutes=5)
        )

        response = self._refresh(tokens["refresh_token"])
        self.assertEqual(response.json()["error"], "invalid_grant")
        # The thief's replay also kills the legitimate client's tokens.
        self.assertEqual(self._mcp(rotated["access_token"]).status_code, 401)
        self.assertEqual(
            self._refresh(rotated["refresh_token"]).json()["error"], "invalid_grant"
        )

    def test_refresh_reuse_within_grace_keeps_the_connection(self):
        tokens = self._exchange(self._approve()["code"]).json()
        rotated = self._refresh(tokens["refresh_token"]).json()

        self.assertEqual(
            self._refresh(tokens["refresh_token"]).json()["error"], "invalid_grant"
        )
        self.assertEqual(self._mcp(rotated["access_token"]).status_code, 200)

    def test_expired_access_token_gets_401(self):
        tokens = self._exchange(self._approve()["code"]).json()
        OAuthToken.objects.update(access_expires_at=timezone.now())
        self.assertEqual(self._mcp(tokens["access_token"]).status_code, 401)

    def test_token_endpoint_errors(self):
        response = self.client.post("/oauth/token/", {"grant_type": "password"})
        self.assertEqual(response.json()["error"], "unsupported_grant_type")
        response = self.client.post("/oauth/token/", {"grant_type": "refresh_token"})
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(self._refresh("bsrt_unknown").json()["error"], "invalid_grant")

    def test_oauth_token_does_not_open_the_rest_of_the_api(self):
        tokens = self._exchange(self._approve()["code"]).json()
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        self.assertEqual(api.get("/api/auth/me/").status_code, 401)

    def test_web_logout_does_not_affect_oauth(self):
        tokens = self._exchange(self._approve()["code"]).json()
        web_token = Token.objects.create(user=self.user)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Token {web_token.key}")
        api.post("/api/auth/logout/")
        self.assertEqual(self._mcp(tokens["access_token"]).status_code, 200)

    # --- connected apps -------------------------------------------------

    def test_list_and_revoke_connections(self):
        tokens = self._exchange(self._approve()["code"]).json()
        self._refresh(tokens["refresh_token"])  # still one connection

        api = APIClient()
        api.force_authenticate(self.user)
        connections = api.get("/api/oauth/connections/").json()["data"]["connections"]
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0]["client_name"], "Claude")

        other_user_api = APIClient()
        other_user_api.force_authenticate(UserFactory())
        response = other_user_api.post(
            "/api/oauth/connections/revoke/",
            {"family_id": connections[0]["family_id"]},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

        response = api.post(
            "/api/oauth/connections/revoke/",
            {"family_id": connections[0]["family_id"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            api.get("/api/oauth/connections/").json()["data"]["connections"], []
        )
