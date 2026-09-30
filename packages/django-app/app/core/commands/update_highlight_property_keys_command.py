from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateHighlightPropertyKeysForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateHighlightPropertyKeysCommand(AbstractBaseCommand):
    """Update whether a property's `key::` renders as a highlighted chip."""

    def __init__(self, form: UpdateHighlightPropertyKeysForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        # BaseForm.clean() drops keys that weren't submitted, so an
        # unchecked box (which posts nothing) reads as "off" here — same
        # convention as UpdateRenderEmojiCommand.
        highlight_property_keys = bool(
            self.form.cleaned_data.get("highlight_property_keys")
        )

        return UserRepository.update_highlight_property_keys(
            user, highlight_property_keys
        )
