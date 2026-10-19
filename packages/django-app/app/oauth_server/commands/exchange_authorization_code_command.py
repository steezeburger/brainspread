from typing import Any

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..errors import OAuthError
from ..forms import ExchangeAuthorizationCodeForm
from ..helpers import hash_secret, is_mcp_resource, verify_pkce_s256
from ..models import OAuthAuthorizationCode
from ..repositories import OAuthAuthorizationCodeRepository, OAuthTokenRepository
from .token_issuance import TokenResponse, issue_token_pair


class ExchangeAuthorizationCodeCommand(AbstractBaseCommand):
    """``grant_type=authorization_code``: trade a code + PKCE verifier
    for the first token pair of a new connection."""

    def __init__(self, form: ExchangeAuthorizationCodeForm) -> None:
        self.form = form

    def execute(self) -> TokenResponse:
        super().execute()
        data = self.form.cleaned_data

        with transaction.atomic():
            code = OAuthAuthorizationCodeRepository.get_by_hash_for_update(
                hash_secret(data["code"])
            )
            if code is None:
                raise OAuthError("invalid_grant", "Unknown authorization code")
            replayed = code.used_at is not None
            if not replayed:
                return self._exchange(code, data)

        # A replayed code may mean it leaked: revoke what it minted. Done
        # after the transaction so raising can't roll the revocation back.
        if code.token_family_id:
            OAuthTokenRepository.revoke_family(code.token_family_id)
        raise OAuthError("invalid_grant", "Authorization code already used")

    def _exchange(
        self, code: OAuthAuthorizationCode, data: dict[str, Any]
    ) -> TokenResponse:
        if code.expires_at <= timezone.now():
            raise OAuthError("invalid_grant", "Authorization code expired")
        if code.client.client_id != data["client_id"]:
            raise OAuthError("invalid_grant", "Code was issued to another client")
        if code.redirect_uri != data["redirect_uri"]:
            raise OAuthError("invalid_grant", "redirect_uri doesn't match")
        if not verify_pkce_s256(data["code_verifier"], code.code_challenge):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        resource = data.get("resource") or code.resource
        if resource and not is_mcp_resource(resource):
            raise OAuthError("invalid_target", "Unknown resource")
        if not code.user.is_active:
            raise OAuthError("invalid_grant", "User is inactive")

        token, response = issue_token_pair(
            user=code.user,
            client=code.client,
            scope=code.scope,
            resource=resource,
        )
        OAuthAuthorizationCodeRepository.mark_used(code, token.family_id)
        return response
