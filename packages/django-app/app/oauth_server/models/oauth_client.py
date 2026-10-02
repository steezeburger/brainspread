from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class OAuthClient(UUIDModelMixin, CRUDTimestampsMixin):
    """A client registered through Dynamic Client Registration (RFC 7591).

    Every client is public (``token_endpoint_auth_method: none``) and
    proves possession with PKCE instead of a secret — that's how Claude
    registers. Claude registers a fresh client on each new connection,
    so these accumulate; they're harmless without a user's consent.
    """

    client_id = models.CharField(max_length=64, unique=True)
    client_name = models.CharField(max_length=200, blank=True)
    redirect_uris = models.JSONField(default=list)

    class Meta:
        db_table = "oauth_clients"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.client_name or self.client_id

    @property
    def display_name(self) -> str:
        return self.client_name or "an unnamed app"
