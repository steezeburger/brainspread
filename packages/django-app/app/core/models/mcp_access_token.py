from typing import Optional, TypedDict

from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class McpAccessToken(UUIDModelMixin, CRUDTimestampsMixin):
    """A named, long-lived credential for the MCP endpoint.

    Separate from the DRF ``Token`` the web app logs in with: that one
    is shared by every browser and deleted on logout, which used to
    break every MCP client configured with it. These are minted one per
    machine / Claude instance, survive web logouts, and are revoked
    individually.

    Only a SHA-256 of the key is stored; the plaintext is shown once at
    creation. ``key_prefix`` is kept so the settings UI can tell tokens
    apart.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_access_tokens",
    )
    name = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=16)
    key_hash = models.CharField(max_length=64, unique=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_access_tokens"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix}…)"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def to_dict(self) -> "McpAccessTokenData":
        return {
            "uuid": str(self.uuid),
            "name": self.name,
            "key_prefix": self.key_prefix,
            "created_at": self.created_at.isoformat(),
            "last_used_at": _iso(self.last_used_at),
            "expires_at": _iso(self.expires_at),
            "is_expired": self.is_expired,
        }


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


class McpAccessTokenData(TypedDict):
    uuid: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    is_expired: bool
