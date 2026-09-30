from datetime import datetime
from typing import Dict, List

from common.repositories.base_repository import BaseRepository

from ..models import AutomationBlockMatch


class AutomationBlockMatchRepository(BaseRepository):
    model = AutomationBlockMatch

    @classmethod
    def get_for_automation(
        cls, automation_block_uuid: str
    ) -> Dict[str, AutomationBlockMatch]:
        """Every tracked dwell row for one automation, keyed by the
        matched block's uuid (string) so ``services.automation_when
        .sync_dwell`` can look each one up while syncing a fresh tick's
        match set."""
        rows = cls.get_queryset().filter(automation_block_uuid=automation_block_uuid)
        return {str(row.matched_block_uuid): row for row in rows}

    @classmethod
    def upsert(
        cls,
        *,
        user,
        automation_block_uuid: str,
        matched_block_uuid: str,
        first_matched_at: datetime,
        fingerprint: dict,
    ) -> AutomationBlockMatch:
        obj, _ = cls.model.objects.update_or_create(
            automation_block_uuid=automation_block_uuid,
            matched_block_uuid=matched_block_uuid,
            defaults={
                "user": user,
                "first_matched_at": first_matched_at,
                "fingerprint": fingerprint,
            },
        )
        return obj

    @classmethod
    def delete_stale(
        cls, automation_block_uuid: str, stale_block_uuids: List[str]
    ) -> None:
        """Drop dwell rows for blocks that no longer match this tick's
        query — leaving the match set resets the dwell clock for next
        time (see automation_when.sync_dwell)."""
        if not stale_block_uuids:
            return
        cls.get_queryset().filter(
            automation_block_uuid=automation_block_uuid,
            matched_block_uuid__in=stale_block_uuids,
        ).delete()
