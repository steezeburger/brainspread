from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import ReorderFavoritedChatSessionsForm
from ..repositories import ChatSessionRepository


class ReorderFavoritedChatSessionsCommand(AbstractBaseCommand):
    """Persist a new drag-sorted order for the user's favorited chats.

    The payload is the desired full ordering. Any favorited chat the
    caller omits keeps its old relative position behind the ones they
    did list — a partial payload won't silently demote a chat off the
    Pinned section. Cross-user / unknown uuids are rejected loudly so
    a stale tab racing a delete surfaces the error instead of
    silently dropping rows.
    """

    def __init__(self, form: ReorderFavoritedChatSessionsForm) -> None:
        self.form = form

    def execute(self) -> List[Dict[str, Any]]:
        super().execute()

        user = self.form.cleaned_data["user"]
        ordered_uuids: List[str] = self.form.cleaned_data["session_uuids"]

        favorited = ChatSessionRepository.list_favorited(user)
        session_by_uuid = {str(s.uuid): s for s in favorited}

        unknown = [u for u in ordered_uuids if u not in session_by_uuid]
        if unknown:
            raise ValidationError(
                "One or more chats are not in your favorites: " + ", ".join(unknown)
            )

        # Apply the requested order, then append any favorites the caller
        # omitted so we never lose them. The omitted ones keep their
        # existing relative order.
        seen = set(ordered_uuids)
        omitted = [str(s.uuid) for s in favorited if str(s.uuid) not in seen]
        new_order = ordered_uuids + omitted

        with transaction.atomic():
            for index, session_uuid in enumerate(new_order):
                session = session_by_uuid[session_uuid]
                if session.favorite_position == index:
                    continue
                session.favorite_position = index
                # Skip modified_at so a reorder doesn't bubble the
                # whole Pinned section to the top of the chronological
                # half of the list.
                session.save(update_fields=["favorite_position"])

        return [
            {
                "uuid": str(s.uuid),
                "favorite_position": s.favorite_position,
            }
            for s in ChatSessionRepository.list_favorited(user)
        ]
