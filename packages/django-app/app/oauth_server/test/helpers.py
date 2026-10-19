import base64
import hashlib
import secrets

from factory import Faker, LazyFunction
from factory.django import DjangoModelFactory

from oauth_server.constants import CLIENT_ID_PREFIX
from oauth_server.models import OAuthClient

CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class OAuthClientFactory(DjangoModelFactory):
    client_id = LazyFunction(lambda: CLIENT_ID_PREFIX + secrets.token_urlsafe(16))
    client_name = Faker("word")
    redirect_uris = LazyFunction(lambda: [CLAUDE_CALLBACK])

    class Meta:
        model = OAuthClient


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge
