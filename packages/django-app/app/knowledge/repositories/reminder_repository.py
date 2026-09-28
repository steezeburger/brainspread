from typing import List

from django.utils import timezone

from common.repositories.base_repository import BaseRepository

from ..models import Reminder


class ReminderRepository(BaseRepository):
    model = Reminder

    @classmethod
    def cancel(cls, reminder: Reminder) -> Reminder:
        """Mark `reminder` cancelled. Sets sent_at alongside status so
        the block-level pending-reminder lookup (which keys off sent_at
        IS NULL) treats it as no-longer-pending."""
        reminder.status = Reminder.STATUS_CANCELLED
        reminder.sent_at = timezone.now()
        reminder.save(update_fields=["status", "sent_at", "modified_at"])
        return reminder

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
