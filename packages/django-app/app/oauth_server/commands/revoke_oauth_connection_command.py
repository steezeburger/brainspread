from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import RevokeOAuthConnectionForm
from ..repositories import OAuthTokenRepository


class RevokeOAuthConnectionCommand(AbstractBaseCommand):
    """Disconnect an app: revoke every token in the connection. The
    client's next call gets a 401 and its refresh gets invalid_grant."""

    def __init__(self, form: RevokeOAuthConnectionForm) -> None:
        self.form = form

    def execute(self) -> None:
        super().execute()
        user = self.form.cleaned_data["user"]
        family_id = self.form.cleaned_data["family_id"]
        if not OAuthTokenRepository.family_exists_for_user(family_id, user):
            raise ValidationError("Connection not found")
        OAuthTokenRepository.revoke_family(family_id, user=user)
