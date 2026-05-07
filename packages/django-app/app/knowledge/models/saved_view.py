from typing import Any, Dict, List, Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin

# Slugs of the bundled system views — referenced by the daily page swap
# so the lookup is name-stable across deploys / data migrations. The
# seed migration upserts on (user, slug, is_system=True).
SYSTEM_VIEW_OVERDUE = "overdue"
SYSTEM_VIEW_DONE_THIS_WEEK = "done-this-week"


class SavedView(UUIDModelMixin, CRUDTimestampsMixin):
    """A user-defined (or seeded) saved query against the user's blocks.

    The structured `filter` JSON is interpreted by the QueryEngine — see
    knowledge/services/query_engine.py for the schema. `is_system` views
    are bundled by the seed migration; users can clone but not edit or
    delete them.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_views",
    )
    name = models.CharField(max_length=200, help_text="Human-readable view name")
    slug = models.SlugField(
        max_length=200,
        help_text="URL-friendly identifier, unique per user",
    )
    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional one-liner shown alongside the view",
    )
    filter = models.JSONField(
        default=dict,
        help_text="Structured filter spec — see knowledge.services.query_engine",
    )
    sort = models.JSONField(
        default=list,
        blank=True,
        help_text='Ordering, e.g. [{"field": "scheduled_for", "dir": "asc"}]',
    )
    is_system = models.BooleanField(
        default=False,
        help_text="Bundled view — read-only for users; cloned via 'duplicate'",
    )

    class Meta:
        db_table = "saved_views"
        unique_together = [("user", "slug")]
        ordering = ("-is_system", "name")
        indexes = [
            models.Index(fields=["user", "is_system"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} - {self.name}"

    def to_dict(self) -> "SavedViewData":
        return {
            "uuid": str(self.uuid),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "filter": self.filter or {},
            "sort": self.sort or [],
            "is_system": self.is_system,
            "user_uuid": str(self.user.uuid),
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
        }


class SavedViewData(TypedDict):
    uuid: str
    name: str
    slug: str
    description: str
    filter: Dict[str, Any]
    sort: List[Dict[str, Any]]
    is_system: bool
    user_uuid: str
    created_at: str
    modified_at: str


class SavedViewListData(TypedDict):
    views: List[SavedViewData]


class SavedViewRunData(TypedDict):
    """Payload returned by RunSavedViewCommand — view + matched blocks."""

    view: SavedViewData
    count: int
    results: List[Dict[str, Any]]
    truncated: bool


# Forward refs for typing in tests / commands without importing both ways
RunResult = Optional[SavedViewRunData]
