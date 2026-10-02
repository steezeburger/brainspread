import uuid
from typing import Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class OAuthToken(UUIDModelMixin, CRUDTimestampsMixin):
    """One access + refresh token pair.

    Refreshing rotates: the old row is marked ``replaced_at`` and a new
    row joins the same ``family_id``. A family is one consent — one
    "connected app" in settings — so revoking a connection revokes the
    family. Only hashes are stored.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
    )
    client = models.ForeignKey(
        "oauth_server.OAuthClient",
        on_delete=models.CASCADE,
        related_name="tokens",
    )
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    access_token_hash = models.CharField(max_length=64, unique=True)
    access_expires_at = models.DateTimeField()
    refresh_token_hash = models.CharField(max_length=64, unique=True)
    refresh_expires_at = models.DateTimeField()
    scope = models.CharField(max_length=200)
    resource = models.TextField(blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # Set when a refresh rotated this pair out.
    replaced_at = models.DateTimeField(null=True, blank=True)
    # Set when the user disconnected the app or reuse was detected.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "oauth_tokens"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.client} for {self.user}"

    def to_connection_dict(self, connected_at) -> "OAuthConnectionData":
        return {
            "family_id": str(self.family_id),
            "client_name": self.client.display_name,
            "connected_at": connected_at.isoformat(),
            "last_used_at": _iso(self.last_used_at),
        }


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


class OAuthConnectionData(TypedDict):
    family_id: str
    client_name: str
    connected_at: str
    last_used_at: Optional[str]
