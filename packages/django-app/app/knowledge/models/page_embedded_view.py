from typing import TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin

SCOPE_PAGE = "page"
SCOPE_DAILY = "daily"
SCOPE_CHOICES = [
    (SCOPE_PAGE, "Page"),
    (SCOPE_DAILY, "Daily"),
]


class PageEmbeddedView(UUIDModelMixin, CRUDTimestampsMixin):
    """A SavedView embedded on a Page as a pinned widget.

    Replaces the earlier ``Block(block_type='query')`` shape: an embed is
    not a block — it has no ``content``, no ``parent``, no ``properties``;
    it's a small pointer record that says "render this view's results
    here, in this order, in this collapsed state."

    ``scope`` controls which pages render the embed. ``"page"`` is the
    classic per-page embed (``page`` FK required). ``"daily"`` embeds
    are pinned to "the daily page" as a concept rather than to a
    specific date — they render on whichever daily page the user is
    viewing, so an embed added from yesterday's daily still shows up
    on today's. For daily-scoped rows the ``page`` FK is null.
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
        null=True,
        blank=True,
    )
    saved_view = models.ForeignKey(
        "knowledge.SavedView",
        on_delete=models.CASCADE,
        related_name="embedded_on",
        help_text="The view whose results render in this slot",
    )
    scope = models.CharField(
        max_length=16,
        choices=SCOPE_CHOICES,
        default=SCOPE_PAGE,
        help_text=(
            "'page' = pinned to one specific Page; 'daily' = pinned to "
            "the daily page concept, renders on whichever daily is open"
        ),
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within the embedded-views section",
    )
    collapsed = models.BooleanField(
        default=False,
        help_text="When true, the embed renders header-only on the page",
    )

    class Meta:
        db_table = "page_embedded_views"
        ordering = ("order", "created_at")
        indexes = [
            models.Index(fields=["page", "order"], name="page_embed_page_order_idx"),
            models.Index(fields=["user", "scope"], name="page_embed_user_scope_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "saved_view"],
                condition=models.Q(scope="page"),
                name="uniq_embed_page_view_page_scope",
            ),
            models.UniqueConstraint(
                fields=["user", "saved_view"],
                condition=models.Q(scope="daily"),
                name="uniq_embed_user_view_daily_scope",
            ),
        ]

    def __str__(self) -> str:
        target = self.page.title if self.page_id else "<daily>"
        return f"{target} ← {self.saved_view.name}"

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
