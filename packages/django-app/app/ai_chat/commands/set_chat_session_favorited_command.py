from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SetChatSessionFavoritedForm
from ..repositories import ChatSessionRepository


class SetChatSessionFavoritedCommand(AbstractBaseCommand):
    """Toggle a chat session's favorited flag.

    The form validates user ownership of the session before this runs,
    so the command can persist directly without re-authorizing.
    """

    def __init__(self, form: SetChatSessionFavoritedForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        user = self.form.cleaned_data["user"]
        session = self.form.cleaned_data["session"]
        is_favorited = self.form.cleaned_data["is_favorited"]

        updated = ChatSessionRepository.set_favorited(
            uuid=str(session.uuid), user=user, is_favorited=is_favorited
        )
        return {
            "uuid": str(updated.uuid),
            "is_favorited": updated.is_favorited,
        }
