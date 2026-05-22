from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import UpdateChatSessionTitleForm
from ..repositories import ChatSessionRepository


class UpdateChatSessionTitleCommand(AbstractBaseCommand):
    """Rename a chat session.

    The form validates user ownership of the session and rejects blank
    titles, so this command can persist directly.
    """

    def __init__(self, form: UpdateChatSessionTitleForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        user = self.form.cleaned_data["user"]
        session = self.form.cleaned_data["session"]
        title = self.form.cleaned_data["title"]

        updated = ChatSessionRepository.update_title(
            uuid=str(session.uuid), user=user, title=title
        )
        return {
            "uuid": str(updated.uuid),
            "title": updated.title,
        }
