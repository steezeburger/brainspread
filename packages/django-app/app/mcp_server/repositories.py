"""Data access for OAuth client (Application) records.

MCP clients register themselves dynamically (RFC 7591), so every
connector that connects creates one ``oauth2_provider`` Application
row. All access to that model is funneled through here.
"""

from typing import Optional

from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import get_application_model

from common.repositories.base_repository import BaseRepository

Application = get_application_model()


class OAuthApplicationRepository(BaseRepository):
    model = Application

    @classmethod
    def create_client(
        cls,
        *,
        name: str,
        redirect_uris: list[str],
        confidential: bool,
    ) -> tuple[Application, Optional[str]]:
        """Register a new authorization-code client.

        Returns the saved Application plus the plaintext client secret
        for confidential clients (DOT hashes the stored copy, so the
        plaintext is only available here at creation time). Public
        clients authenticate with PKCE and get no secret.
        """
        secret_plaintext = generate_client_secret() if confidential else None
        fields = {
            "name": name,
            "redirect_uris": " ".join(redirect_uris),
            "client_type": (
                cls.model.CLIENT_CONFIDENTIAL
                if confidential
                else cls.model.CLIENT_PUBLIC
            ),
            "authorization_grant_type": cls.model.GRANT_AUTHORIZATION_CODE,
            "skip_authorization": False,
        }
        if confidential:
            fields["client_secret"] = secret_plaintext
        application = cls.model.objects.create(**fields)
        return application, secret_plaintext

    @classmethod
    def get_by_client_id(cls, *, client_id: str) -> Optional[Application]:
        try:
            return cls.model.objects.get(client_id=client_id)
        except cls.model.DoesNotExist:
            return None
