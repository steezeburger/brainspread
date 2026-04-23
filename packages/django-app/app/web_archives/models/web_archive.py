from typing import List, Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class WebArchive(UUIDModelMixin, CRUDTimestampsMixin):
    """
    A captured copy of a webpage, tied to a Block. Stores extracted metadata
    plus FKs to Asset rows for the readable HTML, raw HTML, and (eventually)
    a screenshot. Capture runs asynchronously: rows start in `pending`,
    flip to `ready` or `failed`.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("ready", "Ready"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="web_archives",
    )
    # One archive per Block. If we ever want versioned re-captures, switch
    # to FK + a latest_per_block filter; for v1 keep it one-to-one.
    block = models.OneToOneField(
        "knowledge.Block", on_delete=models.CASCADE, related_name="web_archive"
    )

    source_url = models.URLField(max_length=2048)
    canonical_url = models.URLField(max_length=2048, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    failure_reason = models.TextField(blank=True)

    # Extracted metadata
    title = models.CharField(max_length=500, blank=True)
    site_name = models.CharField(max_length=200, blank=True)
    author = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    og_image_url = models.URLField(max_length=2048, blank=True)
    favicon_url = models.URLField(max_length=2048, blank=True)
    excerpt = models.TextField(blank=True)
    word_count = models.PositiveIntegerField(null=True, blank=True)

    # Plain-text body, ready for FTS / vector indexing. Kept inline rather
    # than only in an Asset so text searches stay in Postgres.
    extracted_text = models.TextField(blank=True)
    text_sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    # Artifact references
    readable_asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    raw_asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    screenshot_asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "web_archives"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "status"], name="webarchives_user_status_idx"),
            models.Index(fields=["text_sha256"], name="webarchives_text_sha256_idx"),
        ]

    def __str__(self) -> str:
        return f"WebArchive {self.uuid} ({self.status}): {self.source_url[:80]}"

    def to_dict(self) -> "WebArchiveData":
        return {
            "uuid": str(self.uuid),
            "block_uuid": str(self.block.uuid),
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "title": self.title,
            "site_name": self.site_name,
            "author": self.author,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "og_image_url": self.og_image_url,
            "favicon_url": self.favicon_url,
            "excerpt": self.excerpt,
            "word_count": self.word_count,
            "readable_asset_uuid": (
                str(self.readable_asset.uuid) if self.readable_asset_id else None
            ),
            "created_at": self.created_at.isoformat(),
            "captured_at": (self.captured_at.isoformat() if self.captured_at else None),
        }


class WebArchiveData(TypedDict):
    uuid: str
    block_uuid: str
    source_url: str
    canonical_url: str
    status: str
    failure_reason: str
    title: str
    site_name: str
    author: str
    published_at: Optional[str]
    og_image_url: str
    favicon_url: str
    excerpt: str
    word_count: Optional[int]
    readable_asset_uuid: Optional[str]
    created_at: str
    captured_at: Optional[str]


class WebArchiveListData(TypedDict):
    web_archives: List[WebArchiveData]
    total_count: int
