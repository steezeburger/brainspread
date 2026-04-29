from django.contrib import admin

from .models import Block, Page, Reminder


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "short_uuid",
        "user",
        "slug",
        "page_type",
        "date",
        "created_at",
        "modified_at",
    )
    list_filter = ("page_type", "created_at", "modified_at")
    search_fields = ("title", "user__email", "slug")
    readonly_fields = ("id", "uuid", "created_at", "modified_at")
    raw_id_fields = ("user",)
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("title",)

    def get_tags(self, obj):
        return ", ".join([f"#{tag.name}" for tag in obj.get_tags()])

    get_tags.short_description = "Page Tags"


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = (
        "content_preview",
        "short_uuid",
        "user",
        "page",
        "get_tagged_pages",
        "parent",
        "block_type",
        "content_type",
        "order",
        "scheduled_for",
        "completed_at",
        "created_at",
    )
    list_filter = (
        "block_type",
        "content_type",
        "scheduled_for",
        "created_at",
        "modified_at",
    )
    search_fields = ("content", "user__email", "page__title")
    readonly_fields = ("id", "uuid", "created_at", "modified_at")
    raw_id_fields = ("user", "parent", "page")
    ordering = ("page", "order")

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("user", "page", "parent", "order", "collapsed")},
        ),
        ("Content", {"fields": ("content", "content_type", "block_type")}),
        (
            "Scheduling",
            {
                "fields": ("scheduled_for", "completed_at"),
                "description": (
                    "scheduled_for is the daily page this block should "
                    "surface on. completed_at is set automatically on "
                    "transition to a terminal block_type (done/wontdo)."
                ),
            },
        ),
        (
            "Tags/Pages",
            {
                "fields": ("pages",),
                "description": "Pages this block is tagged with (many-to-many relationship)",
            },
        ),
        (
            "Properties",
            {
                "fields": ("properties",),
                "description": 'Key-value properties as JSON (e.g., {"priority": "high", "due": "2023-12-31"})',
            },
        ),
        (
            "Media",
            {
                "fields": ("media_url", "media_file", "media_metadata"),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def content_preview(self, obj):
        if obj.content:
            return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
        elif obj.media_url or obj.media_file:
            return f"[{obj.content_type}] {obj.media_url or 'file'}"
        else:
            return "[empty block]"

    content_preview.short_description = "Content Preview"

    def get_tagged_pages(self, obj):
        return ", ".join([page.title for page in obj.pages.all()])

    get_tagged_pages.short_description = "Tagged Pages"

    def get_tags(self, obj):
        return ", ".join([f"#{tag.name}" for tag in obj.get_tags()])

    get_tags.short_description = "Tags"


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = (
        "short_uuid",
        "block",
        "fire_at",
        "channel",
        "status",
        "sent_at",
        "created_at",
    )
    list_filter = ("status", "channel", "fire_at", "created_at")
    search_fields = (
        "block__content",
        "block__user__email",
        "last_error",
    )
    readonly_fields = ("id", "uuid", "created_at", "modified_at")
    raw_id_fields = ("block",)
    ordering = ("-fire_at",)

    fieldsets = (
        ("Target", {"fields": ("block", "channel")}),
        ("Schedule", {"fields": ("fire_at",)}),
        ("Delivery", {"fields": ("status", "sent_at", "last_error")}),
        (
            "Metadata",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )
