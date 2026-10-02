from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..constants import AUTHORIZATION_CODE_LIFETIME, MCP_SCOPE
from ..forms import ApproveAuthorizationForm
from ..repositories import OAuthAuthorizationCodeRepository
from ..services.secrets import generate_secret, hash_secret


class CreateAuthorizationCodeCommand(AbstractBaseCommand):
    """Record the user's consent as a short-lived, single-use code.
    Returns the plaintext code to send back to the client."""

    def __init__(self, form: ApproveAuthorizationForm) -> None:
        self.form = form

    def execute(self) -> str:
        super().execute()
        data = self.form.cleaned_data
        code = generate_secret()
        OAuthAuthorizationCodeRepository.create(
            code_hash=hash_secret(code),
            client=self.form.client,
            user=data["user"],
            redirect_uri=data["redirect_uri"],
            code_challenge=data["code_challenge"],
            scope=data.get("scope") or MCP_SCOPE,
            resource=data.get("resource") or "",
            expires_at=timezone.now() + AUTHORIZATION_CODE_LIFETIME,
        )
        return code
