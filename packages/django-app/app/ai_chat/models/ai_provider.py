from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class AIProvider(UUIDModelMixin, CRUDTimestampsMixin):
    """Stores configuration for an AI provider"""

    name = models.CharField(max_length=50)
    base_url = models.URLField(blank=True, null=True)

    class Meta:
        db_table = "ai_providers"
        ordering = ("name",)
        verbose_name = "AI Provider"
        verbose_name_plural = "AI Providers"

    def __str__(self) -> str:
        return self.name
