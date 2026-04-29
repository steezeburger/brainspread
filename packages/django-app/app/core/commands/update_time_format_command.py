from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateTimeFormatForm
from ..models.user import User
from ..repositories.user_repository import UserRepository


class UpdateTimeFormatCommand(AbstractBaseCommand):
    """Update the user's 12h vs 24h time-of-day preference."""

    def __init__(self, form: UpdateTimeFormatForm) -> None:
        self.form = form

    def execute(self) -> User:
        super().execute()

        user = self.form.cleaned_data["user"]
        time_format = self.form.cleaned_data["time_format"]

        return UserRepository.update_time_format(user, time_format)
