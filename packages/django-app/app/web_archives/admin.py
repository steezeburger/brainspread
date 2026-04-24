from django.contrib import admin
from django.utils.html import format_html

from .models import WebArchive


@admin.register(WebArchive)
class WebArchiveAdmin(admin.ModelAdmin):
    list_display = (
        "short_uuid",
        "title_short",
        "user",
        "status",
        "is_active",
        "site_name",
        "source_url_short",
        "word_count",
        "captured_at",
        "created_at",
    )
    list_filter = ("status", "is_active", "site_name", "created_at", "deleted_at")
    search_fields = (
        "title",
        "source_url",
        "canonical_url",
        "user__email",
        "text_sha256",
    )
    readonly_fields = (
        "id",
        "uuid",
        "status",
        "failure_reason",
        "text_sha256",
        "word_count",
        "captured_at",
        "created_at",
        "modified_at",
        "deleted_at",
        "is_active",
        "source_url_link",
        "canonical_url_link",
    )
    raw_id_fields = ("user", "block", "readable_asset", "raw_asset", "screenshot_asset")
    ordering = ("-created_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "block",
                    "status",
                    "failure_reason",
                    "source_url",
                    "source_url_link",
                    "canonical_url",
                    "canonical_url_link",
                )
            },
        ),
        (
            "Extracted metadata",
            {
                "fields": (
                    "title",
                    "site_name",
                    "author",
                    "published_at",
                    "og_image_url",
                    "favicon_url",
                    "excerpt",
                    "word_count",
                )
            },
        ),
        (
            "Assets",
            {
                "fields": ("readable_asset", "raw_asset", "screenshot_asset"),
            },
        ),
        (
            "Extracted text",
            {
                "fields": ("extracted_text", "text_sha256"),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "captured_at",
                    "created_at",
                    "modified_at",
                    "deleted_at",
                    "is_active",
                    "id",
                    "uuid",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def title_short(self, obj):
        t = obj.title or ""
        return (t[:80] + "…") if len(t) > 80 else (t or "—")

    title_short.short_description = "Title"

    def source_url_short(self, obj):
        url = obj.source_url or ""
        return (url[:60] + "…") if len(url) > 60 else url

    source_url_short.short_description = "Source URL"

    def source_url_link(self, obj):
        if not obj.source_url:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">{}</a>',
            obj.source_url,
            obj.source_url,
        )

    source_url_link.short_description = "Open source URL"

    def canonical_url_link(self, obj):
        if not obj.canonical_url:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">{}</a>',
            obj.canonical_url,
            obj.canonical_url,
        )

    canonical_url_link.short_description = "Open canonical URL"
