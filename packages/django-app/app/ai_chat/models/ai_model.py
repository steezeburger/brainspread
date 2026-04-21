from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin

from .ai_provider import AIProvider


class AIModel(UUIDModelMixin, CRUDTimestampsMixin):
    """Stores available AI models and their associated providers"""

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Model name (e.g., gpt-4, claude-opus-4-7)",
    )
    provider = models.ForeignKey(
        AIProvider, on_delete=models.CASCADE, related_name="models"
    )
    display_name = models.CharField(
        max_length=200, help_text="Human-readable name for the model"
    )
    description = models.TextField(
        blank=True, help_text="Optional description of the model"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this model is available for use"
    )

    class Meta:
        db_table = "ai_models"
        ordering = ["provider__name", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.provider.name})"
