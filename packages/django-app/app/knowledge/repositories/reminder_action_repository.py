from django.utils import timezone

from common.repositories.base_repository import BaseRepository

from ..models import ReminderAction


class ReminderActionRepository(BaseRepository):
    model = ReminderAction

    @classmethod
    def mark_used(cls, action: ReminderAction, *, now=None) -> ReminderAction:
        """Stamp `used_at` so the token is rejected on any further use."""
        action.used_at = now or timezone.now()
        action.save(update_fields=["used_at", "modified_at"])
        return action
