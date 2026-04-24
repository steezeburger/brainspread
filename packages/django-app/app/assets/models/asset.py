from typing import Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.uuid_mixin import UUIDModelMixin


class Asset(UUIDModelMixin, CRUDTimestampsMixin):
    """
    A stored binary file owned by a user. Generic container for any kind of
    captured or uploaded artifact (web archive HTML, screenshots, user
    uploads, etc.). Consumers reference Assets via FK to keep storage
    concerns in one place; future migrations to S3/Filebase only need to
    flip Django's DEFAULT_FILE_STORAGE without touching the consumer
    models.
    """

    KIND_CHOICES = [
        ("web_archive_readable_html", "Web Archive Readable HTML"),
        ("web_archive_raw_html", "Web Archive Raw HTML"),
        ("web_archive_screenshot", "Web Archive Screenshot"),
        ("upload", "User Upload"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assets"
    )
    kind = models.CharField(max_length=40, choices=KIND_CHOICES)
    file = models.FileField(upload_to="assets/%Y/%m/")
    mime_type = models.CharField(max_length=120, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    # Hex sha256 of the stored bytes. Enables dedupe and lets us verify files.
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    # Original source URL if the asset was captured from the web.
    source_url = models.URLField(max_length=2048, blank=True)
    # Kind-specific metadata (e.g. viewport size for screenshots).
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "assets"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "kind"], name="assets_user_id_kind_idx"),
            models.Index(fields=["sha256"], name="assets_sha256_idx"),
        ]

    def __str__(self) -> str:
        return f"Asset {self.uuid} ({self.kind})"

    def to_dict(self) -> "AssetData":
        return {
            "uuid": str(self.uuid),
            "kind": self.kind,
            "url": self.file.url if self.file else None,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "metadata": self.metadata or {},
            "created_at": self.created_at.isoformat(),
        }


class AssetData(TypedDict):
    uuid: str
    kind: str
    url: Optional[str]
    mime_type: str
    byte_size: int
    sha256: str
    source_url: str
    metadata: dict
    created_at: str
