from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateRenderEmojiForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateRenderEmojiCommand(AbstractBaseCommand):
    """Update whether :shortcode: sequences render as emoji for the user."""

    def __init__(self, form: UpdateRenderEmojiForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        # BaseForm.clean() drops keys that weren't submitted, so an
        # unchecked box (which posts nothing) reads as "off" here — same
        # convention as SetPageFavoritedCommand.
        render_emoji = bool(self.form.cleaned_data.get("render_emoji"))

        return UserRepository.update_render_emoji(user, render_emoji)
