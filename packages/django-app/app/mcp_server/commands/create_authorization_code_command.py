from common.commands.abstract_base_command import AbstractBaseCommand
from mcp_server.forms import CreateAuthorizationCodeForm
from mcp_server.models import OAuthAuthorizationCode
from mcp_server.repositories import OAuthAuthorizationCodeRepository


class CreateAuthorizationCodeCommand(AbstractBaseCommand):
    """Issue a single-use authorization code after the user approves."""

    def __init__(self, form: CreateAuthorizationCodeForm) -> None:
        self.form = form

    def execute(self) -> OAuthAuthorizationCode:
        super().execute()

        return OAuthAuthorizationCodeRepository.create(
            client=self.form.cleaned_data["client"],
            user=self.form.cleaned_data["user"],
            redirect_uri=self.form.cleaned_data["redirect_uri"],
            code_challenge=self.form.cleaned_data["code_challenge"],
            code_challenge_method=self.form.cleaned_data["code_challenge_method"],
        )
