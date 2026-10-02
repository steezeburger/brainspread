from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateHighlightPropertyValuesForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateHighlightPropertyValuesCommand(AbstractBaseCommand):
    """Update whether a property's value renders with a soft highlight."""

    def __init__(self, form: UpdateHighlightPropertyValuesForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        # BaseForm.clean() drops keys that weren't submitted, so an
        # unchecked box (which posts nothing) reads as "off" here — same
        # convention as UpdateRenderEmojiCommand.
        highlight_property_values = bool(
            self.form.cleaned_data.get("highlight_property_values")
        )

        return UserRepository.update_highlight_property_values(
            user, highlight_property_values
        )
