from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..constants import REFRESH_REUSE_GRACE
from ..errors import OAuthError
from ..forms import RefreshOAuthTokenForm
from ..helpers import hash_secret
from ..models import OAuthToken
from ..repositories import OAuthTokenRepository
from .token_issuance import TokenResponse, issue_token_pair


class RefreshOAuthTokenCommand(AbstractBaseCommand):
    """``grant_type=refresh_token``: rotate to a new pair in the same
    connection. Replaying a rotated refresh token outside a short race
    window revokes the whole connection (OAuth 2.1 reuse detection)."""

    def __init__(self, form: RefreshOAuthTokenForm) -> None:
        self.form = form

    def execute(self) -> TokenResponse:
        super().execute()
        data = self.form.cleaned_data

        with transaction.atomic():
            token = OAuthTokenRepository.get_by_refresh_hash_for_update(
                hash_secret(data["refresh_token"])
            )
            if token is None or token.client.client_id != data["client_id"]:
                raise OAuthError("invalid_grant", "Unknown refresh token")
            reused = token.replaced_at is not None
            if not reused:
                return self._rotate(token)

        # Outside the transaction so raising can't roll the revocation back.
        if timezone.now() - token.replaced_at > REFRESH_REUSE_GRACE:
            OAuthTokenRepository.revoke_family(token.family_id)
        raise OAuthError("invalid_grant", "Refresh token already used")

    def _rotate(self, token: OAuthToken) -> TokenResponse:
        if token.revoked_at is not None:
            raise OAuthError("invalid_grant", "Refresh token revoked")
        if token.refresh_expires_at <= timezone.now():
            raise OAuthError("invalid_grant", "Refresh token expired")
        if not token.user.is_active:
            raise OAuthError("invalid_grant", "User is inactive")

        _, response = issue_token_pair(
            user=token.user,
            client=token.client,
            scope=token.scope,
            resource=token.resource,
            family_id=token.family_id,
        )
        OAuthTokenRepository.mark_replaced(token)
        return response
