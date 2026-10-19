from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class OAuthAuthorizationCode(UUIDModelMixin, CRUDTimestampsMixin):
    """A single-use code handed to the client after the user consents.
    Only its hash is stored."""

    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(
        "oauth_server.OAuthClient",
        on_delete=models.CASCADE,
        related_name="authorization_codes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_authorization_codes",
    )
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=200)
    resource = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    # The token family this code was exchanged for, so replaying the
    # code can revoke what it minted (RFC 6749 4.1.2).
    token_family_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "oauth_authorization_codes"
