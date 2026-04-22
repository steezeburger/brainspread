from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin

from .ai_provider import AIProvider


class UserProviderConfig(UUIDModelMixin, CRUDTimestampsMixin):
    """Stores user configuration for each AI provider"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE)
    api_key = models.CharField(max_length=255, blank=True)
    is_enabled = models.BooleanField(default=True)
    enabled_models = models.ManyToManyField(
        "AIModel",
        blank=True,
        help_text="Models that this user has enabled for this provider",
    )

    class Meta:
        db_table = "user_provider_configs"
        unique_together = [("user", "provider")]
        verbose_name = "User Provider Config"
        verbose_name_plural = "User Provider Configs"

    def __str__(self) -> str:
        return f"{self.user.email} - {self.provider.name}"
