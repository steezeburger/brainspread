"""OAuth 2.1 models backing the MCP server's authorization flow.

These exist so remote MCP clients (Claude Desktop / claude.ai custom
connectors) can connect without a manually-copied DRF token. Clients
are *public* (no client secret) and must use PKCE (S256) — the model
shapes follow RFC 6749/7591/7636 with only the fields this server
actually needs.

Tokens are stored as opaque random strings, mirroring how DRF's
``authtoken.Token`` already stores per-user API tokens in this app.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class OAuthClient(UUIDModelMixin, CRUDTimestampsMixin, models.Model):
    """A dynamically-registered OAuth client (RFC 7591).

    Public client only: there is no client secret; possession of a
    registered ``client_id`` grants nothing without completing the
    PKCE authorization-code flow as a logged-in user.
    """

    client_id = models.CharField(max_length=64, unique=True, editable=False)
    client_name = models.CharField(max_length=255)
    redirect_uris = models.JSONField(default=list)

    class Meta:
        db_table = "mcp_oauth_clients"

    def __str__(self) -> str:
        return f"{self.client_name} ({self.client_id})"

    def is_registered_redirect_uri(self, redirect_uri: str) -> bool:
        return redirect_uri in self.redirect_uris


class OAuthAuthorizationCode(UUIDModelMixin, CRUDTimestampsMixin, models.Model):
    """A single-use authorization code bound to a PKCE challenge."""

    code = models.CharField(max_length=128, unique=True, editable=False)
    client = models.ForeignKey(
        OAuthClient, on_delete=models.CASCADE, related_name="authorization_codes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_authorization_codes",
    )
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    code_challenge_method = models.CharField(max_length=10, default="S256")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_oauth_authorization_codes"

    def __str__(self) -> str:
        return f"code for {self.user} via {self.client.client_name}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_at is not None


class OAuthAccessToken(UUIDModelMixin, CRUDTimestampsMixin, models.Model):
    """A bearer access token + its paired refresh token.

    Refresh tokens rotate: exchanging one revokes this row and issues
    a fresh pair, so a leaked refresh token stops working as soon as
    the legitimate client refreshes.
    """

    access_token = models.CharField(max_length=128, unique=True, editable=False)
    refresh_token = models.CharField(max_length=128, unique=True, editable=False)
    client = models.ForeignKey(
        OAuthClient, on_delete=models.CASCADE, related_name="access_tokens"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_access_tokens",
    )
    access_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_oauth_access_tokens"

    def __str__(self) -> str:
        return f"token for {self.user} via {self.client.client_name}"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def access_token_expired(self) -> bool:
        return timezone.now() >= self.access_expires_at
