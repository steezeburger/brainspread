from django.contrib import admin

from .commands.normalize_block_order_command import NormalizeBlockOrderCommand
from .forms.normalize_block_order_form import NormalizeBlockOrderForm
from .models import AutomationRun, Block, Page, Reminder, ReminderAction


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    actions = ("fix_block_ordering",)

    @admin.action(description="Fix block ordering (renumber sibling groups)")
    def fix_block_ordering(self, request, queryset):
        """Repair duplicate/gapped block orders on the selected pages —
        each sibling group renumbers to 0..N-1 by (order, created_at)."""
        pages = 0
        renumbered = 0
        for page in queryset:
            form = NormalizeBlockOrderForm(
                data={"user": page.user_id, "page": str(page.uuid)}
            )
            if not form.is_valid():
                self.message_user(
                    request, f"{page.title}: {form.errors.as_text()}", level="error"
                )
                continue
            result = NormalizeBlockOrderCommand(form).execute()
            pages += 1
            renumbered += result["renumbered"]
        self.message_user(
            request,
            f"Renumbered {renumbered} block(s) across {pages} page(s).",
        )

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
        "created_via",
        "order",
        "due_at",
        "completed_at",
        "created_at",
    )
    list_filter = (
        "block_type",
        "content_type",
        "created_via",
        "due_at",
        "due_at_has_time",
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
                "fields": ("due_at", "due_at_has_time", "completed_at"),
                "description": (
                    "due_at is when this block is due (all-day unless "
                    "due_at_has_time). completed_at is set automatically on "
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
                "fields": ("id", "uuid", "created_via", "created_at", "modified_at"),
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


@admin.register(ReminderAction)
class ReminderActionAdmin(admin.ModelAdmin):
    list_display = (
        "short_uuid",
        "reminder",
        "action",
        "used_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("action", "created_at")
    search_fields = ("token", "reminder__block__user__email")
    readonly_fields = ("id", "uuid", "token", "created_at", "modified_at")
    raw_id_fields = ("reminder",)
    ordering = ("-created_at",)


@admin.register(AutomationRun)
class AutomationRunAdmin(admin.ModelAdmin):
    """Read-only ledger view — runs are written by the automation engine,
    never by hand. The soft automation_block_uuid reference is searchable
    so a definition block's full history is one paste away."""

    list_display = (
        "short_uuid",
        "automation_block_uuid",
        "user",
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "short_error",
    )
    list_filter = ("status", "trigger", "created_at")
    search_fields = ("automation_block_uuid", "user__email", "last_error")
    readonly_fields = (
        "id",
        "uuid",
        "user",
        "automation_block_uuid",
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "last_error",
        "result",
        "trigger_context",
        "created_at",
        "modified_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    @admin.display(description="error")
    def short_error(self, obj: AutomationRun) -> str:
        return (
            (obj.last_error[:80] + "…") if len(obj.last_error) > 80 else obj.last_error
        )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
