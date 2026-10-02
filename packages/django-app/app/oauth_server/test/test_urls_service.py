from django.test import SimpleTestCase

from oauth_server.services.secrets import verify_pkce_s256
from oauth_server.services.urls import (
    is_mcp_resource,
    is_valid_redirect_uri,
    redirect_uri_matches,
)
from oauth_server.test.helpers import pkce_pair


class RedirectUriTests(SimpleTestCase):
    def test_valid_redirect_uris(self):
        self.assertTrue(
            is_valid_redirect_uri("https://claude.ai/api/mcp/auth_callback")
        )
        self.assertTrue(is_valid_redirect_uri("http://localhost/callback"))
        self.assertTrue(is_valid_redirect_uri("http://127.0.0.1:3118/callback"))
        self.assertFalse(is_valid_redirect_uri("http://evil.example/callback"))
        self.assertFalse(is_valid_redirect_uri("https://claude.ai/cb#frag"))
        self.assertFalse(is_valid_redirect_uri("javascript:alert(1)"))

    def test_https_redirects_match_exactly(self):
        registered = ["https://claude.ai/api/mcp/auth_callback"]
        self.assertTrue(
            redirect_uri_matches("https://claude.ai/api/mcp/auth_callback", registered)
        )
        self.assertFalse(
            redirect_uri_matches("https://claude.ai/api/mcp/auth_callback2", registered)
        )
        self.assertFalse(
            redirect_uri_matches(
                "https://claude.ai:8443/api/mcp/auth_callback", registered
            )
        )

    def test_loopback_redirects_ignore_the_port(self):
        registered = ["http://localhost/callback", "http://127.0.0.1/callback"]
        self.assertTrue(
            redirect_uri_matches("http://localhost:3118/callback", registered)
        )
        self.assertTrue(
            redirect_uri_matches("http://127.0.0.1:50000/callback", registered)
        )
        self.assertFalse(
            redirect_uri_matches("http://localhost:3118/other", registered)
        )
        self.assertFalse(
            redirect_uri_matches("http://localhost.evil.com:3118/callback", registered)
        )

    def test_mcp_resource(self):
        self.assertTrue(is_mcp_resource("https://notes.example/api/mcp/"))
        self.assertTrue(is_mcp_resource("https://notes.example/api/mcp"))
        self.assertFalse(is_mcp_resource("https://notes.example/api/other/"))

    def test_pkce_s256(self):
        verifier, challenge = pkce_pair()
        self.assertTrue(verify_pkce_s256(verifier, challenge))
        self.assertFalse(verify_pkce_s256(verifier + "x", challenge))
