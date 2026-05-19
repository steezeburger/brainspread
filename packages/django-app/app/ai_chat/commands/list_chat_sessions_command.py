import re
from typing import Any, Dict, List, Optional

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ListChatSessionsForm
from ..models import ChatMessage, ChatSession
from ..repositories import ChatMessageRepository, ChatSessionRepository

PREVIEW_LEN = 100
SNIPPET_RADIUS = 60
SNIPPET_MAX = 200

# Strip the `**Context from my notes:** ... **My question:**\n` wrapper
# the SendMessage command adds when context blocks are attached, so a
# legacy session without a curated title still produces a readable
# preview instead of a wall of context bullets.
_CONTEXT_WRAPPER_RE = re.compile(
    r"^\*\*Context from my notes:\*\*.*?\*\*My question:\*\*\s*",
    re.DOTALL,
)


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
        favorites_only: bool = bool(self.form.cleaned_data.get("favorites_only"))

        sessions = ChatSessionRepository.list_for_user(
            user, search=search, favorites_only=favorites_only
        )

        sessions_data: List[Dict[str, Any]] = []
        for session in sessions:
            first_message = ChatMessageRepository.first_user_message(session)
            preview = ""
            if first_message and first_message.content:
                content = self._strip_context_wrapper(first_message.content)
                preview = (
                    content[:PREVIEW_LEN] + "..."
                    if len(content) > PREVIEW_LEN
                    else content
                )

            entry: Dict[str, Any] = {
                "uuid": str(session.uuid),
                # Surface the curated title separately from the
                # context-derived fallback so the UI can render a
                # different style for each (and we keep "New Chat"
                # as the last-ditch label).
                "title": session.title or preview or "New Chat",
                "has_title": bool(session.title),
                "is_favorited": bool(session.is_favorited),
                "preview": preview,
                "created_at": session.created_at.isoformat(),
                "modified_at": session.modified_at.isoformat(),
                "message_count": ChatMessageRepository.count_for_session(session),
            }

            if search:
                entry["match_snippet"] = self._build_snippet(session, search)

            sessions_data.append(entry)

        return sessions_data

    @staticmethod
    def _strip_context_wrapper(content: str) -> str:
        """Remove the `**Context from my notes:** ... **My question:**`
        prefix the SendMessage command prepends when context blocks are
        attached, so the preview shows the user's actual question
        instead of the context dump."""
        stripped = _CONTEXT_WRAPPER_RE.sub("", content, count=1)
        return stripped.strip() or content.strip()

    @staticmethod
    def _build_snippet(session: ChatSession, search: str) -> Optional[str]:
        """Return a short excerpt around the first message-content hit,
        or None when only the title matched. The snippet preserves
        case from the source so the matching substring renders the
        same as the user wrote it."""
        match: Optional[ChatMessage] = (
            ChatMessageRepository.first_content_match_in_session(session, search)
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
