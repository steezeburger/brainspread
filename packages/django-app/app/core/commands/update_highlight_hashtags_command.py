from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateHighlightHashtagsForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateHighlightHashtagsCommand(AbstractBaseCommand):
    """Update whether #hashtags render as a highlighted chip for the user."""

    def __init__(self, form: UpdateHighlightHashtagsForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        # BaseForm.clean() drops keys that weren't submitted, so an
        # unchecked box (which posts nothing) reads as "off" here — same
        # convention as UpdateRenderEmojiCommand.
        highlight_hashtags = bool(self.form.cleaned_data.get("highlight_hashtags"))

        return UserRepository.update_highlight_hashtags(user, highlight_hashtags)
