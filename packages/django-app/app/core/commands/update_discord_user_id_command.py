from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateDiscordUserIdForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateDiscordUserIdCommand(AbstractBaseCommand):
    """Update the user's Discord user ID used for @-mentions in reminders."""

    def __init__(self, form: UpdateDiscordUserIdForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        discord_user_id = self.form.cleaned_data.get("discord_user_id") or ""

        return UserRepository.update_discord_user_id(user, discord_user_id)
