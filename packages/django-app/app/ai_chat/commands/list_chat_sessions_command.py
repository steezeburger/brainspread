from typing import Any, Dict, List, Optional

from django.db.models import Q

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ListChatSessionsForm
from ..models import ChatMessage, ChatSession

PREVIEW_LEN = 100
SNIPPET_RADIUS = 60
SNIPPET_MAX = 200


class ListChatSessionsCommand(AbstractBaseCommand):
    """Return the user's chat sessions for the history list, optionally
    filtered by a free-text search.

    Search matches (case-insensitively) on session title and the content
    of any message in the session. When a query is supplied each
    matching session also includes a short snippet around the first hit
    so users can see what they were asking — not just the title and
    first-user-message preview.
    """

    def __init__(self, form: ListChatSessionsForm) -> None:
        self.form = form

    def execute(self) -> List[Dict[str, Any]]:
        super().execute()

        user = self.form.cleaned_data["user"]
        search: str = self.form.cleaned_data.get("search") or ""

        sessions = ChatSession.objects.filter(user=user)

        if search:
            # An OR over title + message content. distinct() because the
            # join through messages can multiply rows when many messages
            # match in one session.
            sessions = sessions.filter(
                Q(title__icontains=search) | Q(messages__content__icontains=search)
            ).distinct()

        sessions = sessions.order_by("-modified_at")

        sessions_data: List[Dict[str, Any]] = []
        for session in sessions:
            first_message = session.messages.filter(role="user").first()
            preview = ""
            if first_message and first_message.content:
                content = first_message.content
                preview = (
                    content[:PREVIEW_LEN] + "..."
                    if len(content) > PREVIEW_LEN
                    else content
                )

            entry: Dict[str, Any] = {
                "uuid": str(session.uuid),
                "title": session.title or preview or "New Chat",
                "preview": preview,
                "created_at": session.created_at.isoformat(),
                "modified_at": session.modified_at.isoformat(),
                "message_count": session.messages.count(),
            }

            if search:
                entry["match_snippet"] = self._build_snippet(session, search)

            sessions_data.append(entry)

        return sessions_data

    @staticmethod
    def _build_snippet(session: ChatSession, search: str) -> Optional[str]:
        """Return a short excerpt around the first message-content hit,
        or None when only the title matched. The snippet preserves
        case from the source so the matching substring renders the
        same as the user wrote it."""
        match: Optional[ChatMessage] = (
            session.messages.filter(content__icontains=search)
            .order_by("created_at")
            .first()
        )
        if not match or not match.content:
            return None

        content = match.content
        idx = content.lower().find(search.lower())
        if idx < 0:
            return content[:SNIPPET_MAX]

        start = max(0, idx - SNIPPET_RADIUS)
        end = min(len(content), idx + len(search) + SNIPPET_RADIUS)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet
