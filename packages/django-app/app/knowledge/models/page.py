import re
import secrets
from typing import List, Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin
from knowledge.models import BlockData

# Sharing constants live with the model so anyone reading Page sees the
# canonical set without grepping forms/commands.
SHARE_MODE_PRIVATE = "private"
SHARE_MODE_LINK = "link"
SHARE_MODE_CHOICES = [
    (SHARE_MODE_PRIVATE, "Private"),
    (SHARE_MODE_LINK, "Anyone with the link"),
]
PUBLICLY_VIEWABLE_SHARE_MODES = {SHARE_MODE_LINK}


def generate_share_token() -> str:
    """URL-safe random token for /knowledge/share/<token>/. ~22 chars."""
    return secrets.token_urlsafe(16)


class Page(UUIDModelMixin, CRUDTimestampsMixin):
    """
    A page is simply a container/namespace for blocks.
    Pages can be daily notes, regular pages, or any other type of content collection.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pages"
    )
    title = models.CharField(max_length=200, help_text="Human-readable page title")
    slug = models.SlugField(max_length=200, help_text="URL-friendly identifier")
    # Used only by `whiteboard` page types — stores a tldraw store snapshot
    # as JSON. All other page types render their body from Block rows and
    # leave this field blank.
    whiteboard_snapshot = models.TextField(
        blank=True, help_text="Tldraw JSON snapshot for whiteboard pages"
    )
    is_published = models.BooleanField(
        default=True, help_text="Whether the page is published"
    )
    page_type = models.CharField(
        max_length=20,
        choices=[
            ("page", "Regular Page"),
            ("daily", "Daily Note"),
            ("template", "Template"),
            ("whiteboard", "Whiteboard"),
        ],
        default="page",
    )
    date = models.DateField(null=True, blank=True, help_text="Date for daily notes")

    # Public sharing. share_token is unguessable and stable across mode
    # toggles so a sender's existing link keeps working when they flip back
    # to "link" sharing after a brief private window. It's lazily generated
    # the first time a user shares the page (see SharePageCommand).
    share_mode = models.CharField(
        max_length=10,
        choices=SHARE_MODE_CHOICES,
        default=SHARE_MODE_PRIVATE,
        help_text="Public visibility of the page",
    )
    share_token = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text="Unguessable token used in public share URLs",
    )

    # User-curated "starred" flag. Pinned pages render in the left-nav
    # Favorites section so the user can jump to their working set without
    # searching. Unrelated to is_published / share_mode.
    favorited = models.BooleanField(
        default=False, help_text="Whether the user has starred this page"
    )
    favorite_position = models.IntegerField(
        default=0,
        help_text=(
            "Order within the user's Favorites list. Lower values appear "
            "first; ties fall back to title."
        ),
    )

    class Meta:
        db_table = "pages"
        unique_together = [("user", "slug")]
        ordering = ("title",)
        indexes = [
            models.Index(fields=["user", "page_type", "date"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.title}"

    def get_tag_format(self) -> str:
        """Generate hashtag format from slug for tag matching: 'my-page' -> '#my-page'"""
        return f"#{self.slug}"

    def get_backlinks(self):
        """Get all blocks that link to this page"""
        from .block import Block

        pattern = r"\[\[" + re.escape(self.title) + r"\]\]"
        return Block.objects.filter(content__iregex=pattern, user=self.user).exclude(
            page=self
        )

    def get_tag_blocks(self):
        """Get all blocks that are tagged with this page"""
        return self.tagged_blocks.all()

    @property
    def is_publicly_viewable(self) -> bool:
        """True when the share_token URL should resolve for anonymous viewers."""
        return self.share_mode in PUBLICLY_VIEWABLE_SHARE_MODES and bool(
            self.share_token
        )

    def to_dict(self) -> "PageData":
        """Convert page to dictionary with proper typing"""
        return {
            "uuid": str(self.uuid),
            "title": self.title,
            "slug": self.slug,
            "whiteboard_snapshot": self.whiteboard_snapshot,
            "is_published": self.is_published,
            "page_type": self.page_type,
            "date": self.date.isoformat() if self.date else None,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "user_uuid": str(self.user.uuid),
            "recent_blocks": None,  # fill these in later
            "share_mode": self.share_mode,
            "share_token": self.share_token,
            "favorited": self.favorited,
        }


# API response type for Page data
class PageData(TypedDict):
    uuid: str
    title: str
    slug: str
    whiteboard_snapshot: str
    is_published: bool
    page_type: str
    date: Optional[str]
    created_at: str
    modified_at: str
    user_uuid: str
    recent_blocks: Optional[List[BlockData]]
    share_mode: str
    share_token: Optional[str]
    favorited: bool


class PagesData(TypedDict):
    pages: List[PageData]
    total_count: int
    has_more: bool


class PageWithBlocksData(TypedDict):
    page: PageData
    direct_blocks: List[BlockData]
    referenced_blocks: List[BlockData]
    overdue_blocks: List[BlockData]
