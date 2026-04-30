from django.contrib import admin
from django.utils.html import format_html

from .models import Asset


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "short_uuid",
        "asset_type",
        "file_type",
        "user",
        "filename",
        "mime_type",
        "human_byte_size",
        "source_url_short",
        "created_at",
    )
    list_filter = ("asset_type", "file_type", "mime_type", "created_at")
    search_fields = ("sha256", "source_url", "user__email", "file", "original_filename")
    readonly_fields = (
        "id",
        "uuid",
        "sha256",
        "byte_size",
        "mime_type",
        "width",
        "height",
        "created_at",
        "modified_at",
        "preview",
    )
    raw_id_fields = ("user",)
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("user", "asset_type", "file_type", "source_url")}),
        (
            "File",
            {
                "fields": (
                    "file",
                    "preview",
                    "original_filename",
                    "mime_type",
                    "byte_size",
                    "sha256",
                    "width",
                    "height",
                )
            },
        ),
        ("Metadata", {"fields": ("metadata",), "classes": ("collapse",)}),
        (
            "Timestamps",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def filename(self, obj):
        if obj.original_filename:
            return obj.original_filename
        if not obj.file:
            return "-"
        # FieldFile.name is the path relative to MEDIA_ROOT; show just the
        # basename so the table stays readable.
        return obj.file.name.rsplit("/", 1)[-1]

    filename.short_description = "File"

    def human_byte_size(self, obj):
        size = obj.byte_size or 0
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    human_byte_size.short_description = "Size"
    human_byte_size.admin_order_field = "byte_size"

    def source_url_short(self, obj):
        url = obj.source_url or ""
        return (url[:60] + "…") if len(url) > 60 else url

    source_url_short.short_description = "Source URL"

    def preview(self, obj):
        """
        Inline rendering of the asset itself so an admin can confirm what
        was actually uploaded without leaving the page. Images render as
        a clickable thumbnail; HTML/PDF/text render in an <iframe> sized
        for a quick read; everything else falls back to a labeled
        download link.

        Uses obj.file.url (raw MEDIA_URL) instead of /api/assets/<uuid>/
        because the serve endpoint enforces per-user ownership - admins
        viewing other users' assets would get 404. Admin is staff-only,
        so the raw media URL is the right primitive here.
        """
        if not obj.file:
            return "-"
        url = obj.file.url
        label = obj.original_filename or url.rsplit("/", 1)[-1]
        file_type = obj.file_type or ""

        if file_type == "image":
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">'
                '<img src="{}" style="max-width: 480px; max-height: 360px; '
                'border: 1px solid #ccc; border-radius: 3px;" alt="{}" />'
                "</a>",
                url,
                url,
                label,
            )
        if (
            file_type in ("html", "pdf")
            or file_type == "other"
            and (obj.mime_type or "").startswith("text/")
        ):
            return format_html(
                '<iframe src="{}" style="width: 100%; max-width: 720px; '
                'height: 360px; border: 1px solid #ccc; border-radius: 3px;"></iframe>'
                '<div style="margin-top: 0.4rem;">'
                '<a href="{}" target="_blank" rel="noopener">open in new tab</a>'
                "</div>",
                url,
                url,
            )
        if file_type == "video":
            return format_html(
                '<video src="{}" controls style="max-width: 480px; max-height: 360px;">'
                "</video>",
                url,
            )
        if file_type == "audio":
            return format_html('<audio src="{}" controls></audio>', url)
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">download {}</a>',
            url,
            label,
        )

    preview.short_description = "Preview"
