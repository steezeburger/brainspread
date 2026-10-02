from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ListOAuthConnectionsForm
from ..models import OAuthConnectionData
from ..repositories import OAuthTokenRepository


class ListOAuthConnectionsCommand(AbstractBaseCommand):
    """Apps the user has connected over OAuth, newest activity first."""

    def __init__(self, form: ListOAuthConnectionsForm) -> None:
        self.form = form

    def execute(self) -> list[OAuthConnectionData]:
        super().execute()
        tokens = list(
            OAuthTokenRepository.list_active_for_user(self.form.cleaned_data["user"])
        )
        started = OAuthTokenRepository.family_started_at([t.family_id for t in tokens])
        return [
            t.to_connection_dict(connected_at=started.get(t.family_id, t.created_at))
            for t in tokens
        ]
