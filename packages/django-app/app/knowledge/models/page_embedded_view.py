from typing import TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class PageEmbeddedView(UUIDModelMixin, CRUDTimestampsMixin):
    """A SavedView embedded on a Page as a pinned widget.

    Replaces the earlier ``Block(block_type='query')`` shape: an embed is
    not a block — it has no ``content``, no ``parent``, no ``properties``;
    it's a small pointer record that says "render this view's results
    here, in this order, in this collapsed state."

    A page holds at most one embed per saved view (enforced by
    ``unique_together``) — repeated "Embed on today" for the same view
    is a misclick, not a feature.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_embedded_views",
    )
    page = models.ForeignKey(
        "knowledge.Page",
        on_delete=models.CASCADE,
        related_name="embedded_views",
    )
    saved_view = models.ForeignKey(
        "knowledge.SavedView",
        on_delete=models.CASCADE,
        related_name="embedded_on",
        help_text="The view whose results render in this slot",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within the page's embedded-views section",
    )
    collapsed = models.BooleanField(
        default=False,
        help_text="When true, the embed renders header-only on the page",
    )

    class Meta:
        db_table = "page_embedded_views"
        unique_together = [("page", "saved_view")]
        ordering = ("order", "created_at")
        indexes = [
            models.Index(fields=["page", "order"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.page.title} ← {self.saved_view.name}"

    def to_dict(self) -> "PageEmbeddedViewData":
        return {
            "uuid": str(self.uuid),
            "order": self.order,
            "collapsed": self.collapsed,
            "saved_view": {
                "uuid": str(self.saved_view.uuid),
                "name": self.saved_view.name,
                "slug": self.saved_view.slug,
            },
        }


class PageEmbeddedViewSavedViewSummary(TypedDict):
    uuid: str
    name: str
    slug: str


class PageEmbeddedViewData(TypedDict):
    uuid: str
    order: int
    collapsed: bool
    saved_view: PageEmbeddedViewSavedViewSummary
