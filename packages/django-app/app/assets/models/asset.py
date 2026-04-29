from typing import Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class Asset(UUIDModelMixin, CRUDTimestampsMixin):
    """
    A stored binary file owned by a user. Generic container for any kind of
    captured or uploaded artifact (web archive HTML, screenshots, user
    uploads, block attachments, whiteboard assets, etc.). Consumers
    reference Assets via FK to keep storage concerns in one place; future
    migrations to S3/Filebase only need to flip Django's
    DEFAULT_FILE_STORAGE without touching the consumer models.

    Two orthogonal classifiers:
      - file_type describes the asset's *shape* (image vs pdf vs html ...).
      - asset_type describes its *purpose* (which subsystem produced it).
    """

    FILE_TYPE_HTML = "html"
    FILE_TYPE_IMAGE = "image"
    FILE_TYPE_PDF = "pdf"
    FILE_TYPE_VIDEO = "video"
    FILE_TYPE_AUDIO = "audio"
    FILE_TYPE_OTHER = "other"
    FILE_TYPE_CHOICES = [
        (FILE_TYPE_HTML, "HTML"),
        (FILE_TYPE_IMAGE, "Image"),
        (FILE_TYPE_PDF, "PDF"),
        (FILE_TYPE_VIDEO, "Video"),
        (FILE_TYPE_AUDIO, "Audio"),
        (FILE_TYPE_OTHER, "Other"),
    ]

    ASSET_TYPE_WEB_ARCHIVE_READABLE = "web_archive_readable"
    ASSET_TYPE_WEB_ARCHIVE_RAW = "web_archive_raw"
    ASSET_TYPE_WEB_ARCHIVE_SCREENSHOT = "web_archive_screenshot"
    ASSET_TYPE_BLOCK_ATTACHMENT = "block_attachment"
    ASSET_TYPE_WHITEBOARD_ASSET = "whiteboard_asset"
    ASSET_TYPE_CHAT_ATTACHMENT = "chat_attachment"
    ASSET_TYPE_UPLOAD = "upload"
    ASSET_TYPE_CHOICES = [
        (ASSET_TYPE_WEB_ARCHIVE_READABLE, "Web Archive Readable HTML"),
        (ASSET_TYPE_WEB_ARCHIVE_RAW, "Web Archive Raw"),
        (ASSET_TYPE_WEB_ARCHIVE_SCREENSHOT, "Web Archive Screenshot"),
        (ASSET_TYPE_BLOCK_ATTACHMENT, "Block Attachment"),
        (ASSET_TYPE_WHITEBOARD_ASSET, "Whiteboard Asset"),
        (ASSET_TYPE_CHAT_ATTACHMENT, "Chat Attachment"),
        (ASSET_TYPE_UPLOAD, "User Upload"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assets"
    )
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES)
    asset_type = models.CharField(max_length=40, choices=ASSET_TYPE_CHOICES)
    file = models.FileField(upload_to="assets/%Y/%m/")
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    # Hex sha256 of the stored bytes. Enables dedupe and lets us verify files.
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    # Pixel dimensions for image/video assets; null for everything else.
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    # Original source URL if the asset was captured from the web.
    source_url = models.URLField(max_length=2048, blank=True)
    # Type-specific metadata (e.g. viewport size for screenshots, page count
    # for PDFs, EXIF for images).
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "assets"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["user", "asset_type"], name="assets_user_id_asset_type_idx"
            ),
            models.Index(fields=["sha256"], name="assets_sha256_idx"),
        ]

    def __str__(self) -> str:
        return f"Asset {self.uuid} ({self.asset_type}/{self.file_type})"

    def to_dict(self) -> "AssetData":
        return {
            "uuid": str(self.uuid),
            "file_type": self.file_type,
            "asset_type": self.asset_type,
            "url": self.file.url if self.file else None,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "source_url": self.source_url,
            "metadata": self.metadata or {},
            "created_at": self.created_at.isoformat(),
        }


class AssetData(TypedDict):
    uuid: str
    file_type: str
    asset_type: str
    url: Optional[str]
    original_filename: str
    mime_type: str
    byte_size: int
    sha256: str
    width: Optional[int]
    height: Optional[int]
    source_url: str
    metadata: dict
    created_at: str


def file_type_from_mime(mime_type: str) -> str:
    """Map a MIME type to one of Asset.FILE_TYPE_CHOICES."""
    if not mime_type:
        return Asset.FILE_TYPE_OTHER
    base = mime_type.split(";", 1)[0].strip().lower()
    if base in ("text/html", "application/xhtml+xml"):
        return Asset.FILE_TYPE_HTML
    if base == "application/pdf":
        return Asset.FILE_TYPE_PDF
    if base.startswith("image/"):
        return Asset.FILE_TYPE_IMAGE
    if base.startswith("video/"):
        return Asset.FILE_TYPE_VIDEO
    if base.startswith("audio/"):
        return Asset.FILE_TYPE_AUDIO
    return Asset.FILE_TYPE_OTHER
