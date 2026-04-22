from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class UserAISettings(UUIDModelMixin, CRUDTimestampsMixin):
    """Stores user-specific AI settings such as preferred model"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    preferred_model = models.ForeignKey(
        "AIModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User's preferred AI model for new conversations",
    )

    class Meta:
        db_table = "user_ai_settings"
        verbose_name = "User AI Settings"
        verbose_name_plural = "User AI Settings"

    def __str__(self) -> str:
        return f"{self.user.email} settings"
