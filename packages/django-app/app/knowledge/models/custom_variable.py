from typing import TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class CustomVariable(UUIDModelMixin, CRUDTimestampsMixin):
    """A user-defined ``{{name}}`` content token (issue #228).

    ``expansion`` is raw text that replaces ``{{name}}`` when block
    content resolves; it may itself contain tokens, built-in or custom,
    which resolve too (see ``services.content_tokens``). ``name`` is
    stored lowercase because the resolver matches token names
    case-insensitively.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_variables",
    )
    name = models.CharField(
        max_length=64,
        help_text="Identifier used inside {{...}}: lowercase letters, digits, _",
    )
    expansion = models.TextField(
        help_text="Text the variable expands to; may contain other {{tokens}}",
    )

    class Meta:
        db_table = "custom_variables"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="uniq_custom_variable_user_name"
            ),
        ]

    def __str__(self) -> str:
        return f"{{{{{self.name}}}}}"

    def to_dict(self) -> "CustomVariableData":
        return {
            "uuid": str(self.uuid),
            "name": self.name,
            "expansion": self.expansion,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
        }


class CustomVariableData(TypedDict):
    uuid: str
    name: str
    expansion: str
    created_at: str
    modified_at: str
