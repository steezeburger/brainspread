from django.contrib import admin
from django.utils.html import format_html

from .models import Asset


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "short_uuid",
        "kind",
        "user",
        "filename",
        "mime_type",
        "human_byte_size",
        "source_url_short",
        "created_at",
    )
    list_filter = ("kind", "mime_type", "created_at")
    search_fields = ("sha256", "source_url", "user__email", "file")
    readonly_fields = (
        "id",
        "uuid",
        "sha256",
        "byte_size",
        "mime_type",
        "created_at",
        "modified_at",
        "file_link",
    )
    raw_id_fields = ("user",)
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("user", "kind", "source_url")}),
        ("File", {"fields": ("file", "file_link", "mime_type", "byte_size", "sha256")}),
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

    def file_link(self, obj):
        if not obj.file:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">download</a>', obj.file.url
        )

    file_link.short_description = "Download"
