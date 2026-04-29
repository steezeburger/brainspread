from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateDiscordWebhookForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateDiscordWebhookCommand(AbstractBaseCommand):
    """Update the user's Discord reminder webhook URL (see issue #59)."""

    def __init__(self, form: UpdateDiscordWebhookForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        url = self.form.cleaned_data.get("discord_webhook_url") or ""

        return UserRepository.update_discord_webhook_url(user, url)
