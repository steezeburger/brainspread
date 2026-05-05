from typing import List

from common.repositories.base_repository import BaseRepository

from ..models import Reminder


class ReminderRepository(BaseRepository):
    model = Reminder

    @classmethod
    def get_pending_for_user(cls, user, limit: int) -> List[Reminder]:
        """Reminders that haven't fired yet for the user, oldest fire_at
        first. Pre-loads block + page so the chat surface can render the
        row without follow-up queries."""
        return list(
            cls.get_queryset()
            .filter(
                block__user=user,
                sent_at__isnull=True,
                status=Reminder.STATUS_PENDING,
            )
            .select_related("block", "block__page")
            .order_by("fire_at")[:limit]
        )
