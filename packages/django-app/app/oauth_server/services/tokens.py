import uuid
from typing import Optional, TypedDict

from django.utils import timezone

from core.models import User

from ..constants import (
    ACCESS_TOKEN_LIFETIME,
    ACCESS_TOKEN_PREFIX,
    REFRESH_TOKEN_LIFETIME,
    REFRESH_TOKEN_PREFIX,
)
from ..models import OAuthClient, OAuthToken
from ..repositories import OAuthTokenRepository
from .secrets import generate_secret, hash_secret


class TokenResponse(TypedDict):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str


def issue_token_pair(
    *,
    user: User,
    client: OAuthClient,
    scope: str,
    resource: str,
    family_id: Optional[uuid.UUID] = None,
) -> tuple[OAuthToken, TokenResponse]:
    """Mint an access + refresh token pair. Pass ``family_id`` when
    rotating so the pair stays part of the same connection."""
    now = timezone.now()
    access_token = generate_secret(ACCESS_TOKEN_PREFIX)
    refresh_token = generate_secret(REFRESH_TOKEN_PREFIX)
    token = OAuthTokenRepository.create(
        user=user,
        client=client,
        family_id=family_id,
        access_token_hash=hash_secret(access_token),
        access_expires_at=now + ACCESS_TOKEN_LIFETIME,
        refresh_token_hash=hash_secret(refresh_token),
        refresh_expires_at=now + REFRESH_TOKEN_LIFETIME,
        scope=scope,
        resource=resource,
    )
    return token, {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        "refresh_token": refresh_token,
        "scope": scope,
    }
