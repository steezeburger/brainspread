from datetime import datetime
from typing import List, Optional

from common.repositories.base_repository import BaseRepository

from ..models import AutomationRun


class AutomationRunRepository(BaseRepository):
    model = AutomationRun

    @classmethod
    def create(
        cls,
        *,
        user,
        automation_block_uuid: str,
        trigger: str,
        status: str = AutomationRun.STATUS_PENDING,
        started_at: Optional[datetime] = None,
        trigger_context: Optional[dict] = None,
    ) -> AutomationRun:
        return cls.model.objects.create(
            user=user,
            automation_block_uuid=automation_block_uuid,
            trigger=trigger,
            status=status,
            started_at=started_at,
            trigger_context=trigger_context or {},
        )

    @classmethod
    def latest_for_automation(
        cls, automation_block_uuid: str
    ) -> Optional[AutomationRun]:
        """Most recent run for an automation, or None.

        The schedule poller uses this to decide whether a given automation
        is due (compare its cadence against the last run's timestamp)."""
        return (
            cls.get_queryset()
            .filter(automation_block_uuid=automation_block_uuid)
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def list_for_user(cls, user, limit: int = 50) -> List[AutomationRun]:
        return list(
            cls.get_queryset().filter(user=user).order_by("-created_at")[:limit]
        )
