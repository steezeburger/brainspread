from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateHighlightPropertiesForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateHighlightPropertiesCommand(AbstractBaseCommand):
    """Update whether key::value properties render as a highlighted chip."""

    def __init__(self, form: UpdateHighlightPropertiesForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        # BaseForm.clean() drops keys that weren't submitted, so an
        # unchecked box (which posts nothing) reads as "off" here — same
        # convention as UpdateRenderEmojiCommand.
        highlight_properties = bool(self.form.cleaned_data.get("highlight_properties"))

        return UserRepository.update_highlight_properties(user, highlight_properties)
