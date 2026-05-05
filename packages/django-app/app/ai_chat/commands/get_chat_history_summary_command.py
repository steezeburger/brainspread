from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import GetChatHistorySummaryForm
from ..repositories.chat_session_repository import ChatSessionRepository

PREVIEW_LEN = 200


class GetChatHistorySummaryCommand(AbstractBaseCommand):
    """List the user's prior chat sessions with a short summary line
    each. Summary v0 is the first user message preview — enough to jog
    "did I already ask about this?" without populating a real
    LLM-derived summary field.
    """

    def __init__(self, form: GetChatHistorySummaryForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        limit: int = self.form.cleaned_data.get("limit") or 10
        exclude_session_id: str = (
            self.form.cleaned_data.get("exclude_session_id") or ""
        ).strip() or None

        sessions = ChatSessionRepository.get_history_for_user(
            user, limit=limit, exclude_session_id=exclude_session_id
        )

        results: List[Dict[str, Any]] = []
        for session in sessions:
            first_user_message = (
                session.messages.filter(role="user").order_by("created_at").first()
            )
            if first_user_message:
                summary = first_user_message.content.strip()
                if len(summary) > PREVIEW_LEN:
                    summary = summary[: PREVIEW_LEN - 3] + "..."
            else:
                summary = ""
            results.append(
                {
                    "session_uuid": str(session.uuid),
                    "title": session.title or "",
                    "started_at": session.created_at.isoformat(),
                    "message_count": session.message_count,
                    "summary": summary,
                }
            )

        return {
            "count": len(results),
            "results": results,
        }
