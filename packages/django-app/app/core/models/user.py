from typing import TypedDict

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.soft_delete_timestamp_mixin import SoftDeleteTimestampMixin
from common.models.uuid_mixin import UUIDModelMixin
from core.managers import UserManager


class User(
    UUIDModelMixin,
    CRUDTimestampsMixin,
    SoftDeleteTimestampMixin,
    AbstractBaseUser,
    PermissionsMixin,
):
    USERNAME_FIELD = "email"
    objects = UserManager()

    email = models.EmailField(
        verbose_name="email",
        max_length=255,
        unique=True,
    )

    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )

    timezone = models.CharField(
        _("timezone"),
        max_length=50,
        default="UTC",
        help_text=_("User's preferred timezone (e.g., America/New_York, UTC, etc.)"),
    )

    THEME_CHOICES = [
        ("dark", "Dark"),
        ("light", "Light"),
        ("solarized_dark", "Solarized Dark"),
        ("purple", "Purple"),
        ("earthy", "Earthy"),
        ("forest", "Forest"),
    ]

    theme = models.CharField(
        _("theme"),
        max_length=20,
        choices=THEME_CHOICES,
        default="dark",
        help_text=_("User's preferred theme"),
    )

    discord_webhook_url = models.URLField(
        _("discord webhook url"),
        max_length=500,
        blank=True,
        default="",
        help_text=_(
            "Optional Discord webhook URL used to deliver reminders (see issue #59)"
        ),
    )

    discord_user_id = models.CharField(
        _("discord user id"),
        max_length=32,
        blank=True,
        default="",
        help_text=_(
            "Optional Discord user ID (numeric snowflake) — when set, reminder "
            "messages mention this user so they get a push/desktop notification"
        ),
    )

    TIME_FORMAT_CHOICES = [
        ("24h", "24 hour"),
        ("12h", "12 hour"),
    ]

    time_format = models.CharField(
        _("time format"),
        max_length=4,
        choices=TIME_FORMAT_CHOICES,
        default="12h",
        help_text=_("Whether to display times as 24-hour or 12-hour"),
    )

    def __str__(self):
        return self.email

    def to_user_data(self) -> "UserData":
        """Convert User instance to UserData TypedDict"""
        return UserData(
            uuid=str(self.uuid),
            email=self.email,
            is_active=self.is_active,
            timezone=self.timezone,
            theme=self.theme,
            discord_webhook_url=self.discord_webhook_url,
            discord_user_id=self.discord_user_id,
            time_format=self.time_format,
            created_at=self.created_at.isoformat(),
        )

    class Meta:
        db_table = "users"
        default_permissions = ()
        unique_together = []
        ordering = ("id",)


# API response type for User data
class UserData(TypedDict):
    uuid: str
    email: str
    is_active: bool
    timezone: str
    theme: str
    discord_webhook_url: str
    discord_user_id: str
    time_format: str
    created_at: str
