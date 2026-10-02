from common.commands.abstract_base_command import AbstractBaseCommand

from ..constants import CLIENT_ID_PREFIX
from ..forms import RegisterOAuthClientForm
from ..models import OAuthClient
from ..repositories import OAuthClientRepository
from ..services.secrets import generate_secret


class RegisterOAuthClientCommand(AbstractBaseCommand):
    """Dynamic Client Registration (RFC 7591) for a public PKCE client."""

    def __init__(self, form: RegisterOAuthClientForm) -> None:
        self.form = form

    def execute(self) -> OAuthClient:
        super().execute()
        return OAuthClientRepository.create(
            client_id=generate_secret(CLIENT_ID_PREFIX),
            client_name=self.form.cleaned_data.get("client_name") or "",
            redirect_uris=self.form.cleaned_data["redirect_uris"],
        )
