"""Execute assistant-requested notes tool calls.

Thin wrapper over the shared notes tool registry: it holds the
per-request context (the acting user, the page they have open, and the
write-approval flags) and delegates dispatch to ``NOTES_REGISTRY``. Each
tool resolves to a Form + Command pair in ``notes_handlers``; all
business logic lives in the commands themselves.

Write tools never run without explicit user approval — the service
pauses and the execution happens out-of-band during resume. See
ai_chat.commands.resume_approval_command.
"""

import logging
from typing import Any, Dict, Optional

from core.llm_tools import ToolContext, ToolError
from core.models import User

from .notes_tools import NOTES_REGISTRY

logger = logging.getLogger(__name__)


class NotesToolExecutor:
    """Dispatches a custom tool call against the user's knowledge graph.

    `allow_writes` controls whether write tools are known at all.
    `auto_approve_writes` opts out of the per-call approval gate — writes
    execute inline like reads. This is opt-in per request; default keeps
    the safer manual-approval flow.
    """

    def __init__(
        self,
        user: User,
        allow_writes: bool = False,
        auto_approve_writes: bool = False,
        current_page_uuid: Optional[str] = None,
    ) -> None:
        self.user = user
        self.allow_writes = allow_writes
        self.auto_approve_writes = auto_approve_writes
        # Set by send_message_command from the chat request payload —
        # the page the user has open in the UI when they send a
        # message. Used by the get_current_page tool. None when the
        # user is on a non-page surface (graph view, etc).
        self.current_page_uuid = current_page_uuid

    def is_known(self, name: str) -> bool:
        tool = NOTES_REGISTRY.get(name)
        if tool is None:
            return False
        if tool.is_write:
            return self.allow_writes
        return True

    def requires_approval(self, name: str) -> bool:
        if self.auto_approve_writes:
            return False
        tool = NOTES_REGISTRY.get(name)
        return bool(tool and tool.is_write)

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        ctx = ToolContext(user=self.user, current_page_uuid=self.current_page_uuid)
        try:
            return NOTES_REGISTRY.execute(name, ctx, args)
        except ToolError as e:
            # Unknown tool — surface as a recoverable error dict.
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Notes tool %s failed", name)
            return {"error": f"Tool {name} failed: {e}"}
