from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    AIModel,
    AIProvider,
    ChatMessage,
    ChatSession,
    UserAISettings,
    UserProviderConfig,
)


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    list_display = ["name", "short_uuid", "base_url", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["name"]
    readonly_fields = ["id", "uuid", "created_at", "modified_at"]

    fieldsets = (
        (None, {"fields": ("name", "base_url")}),
        (
            "Metadata",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "short_uuid",
        "provider",
        "display_name",
        "is_active",
        "created_at",
    ]
    list_filter = ["provider", "is_active", "created_at"]
    search_fields = ["name", "display_name", "description"]
    readonly_fields = ["id", "uuid", "created_at", "modified_at"]
    raw_id_fields = ["provider"]

    fieldsets = (
        (None, {"fields": ("name", "provider", "display_name", "is_active")}),
        (
            "Description",
            {"fields": ("description",), "classes": ("wide",)},
        ),
        (
            "Metadata",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ["id", "created_at", "content_preview"]
    fields = ["role", "content_preview", "created_at"]

    def content_preview(self, obj):
        if obj.content:
            preview = (
                obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
            )
            return format_html(
                '<div style="max-width: 300px; white-space: pre-wrap;">{}</div>',
                preview,
            )
        return "-"

    content_preview.short_description = "Content Preview"


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = [
        "title_or_id",
        "short_uuid",
        "user",
        "message_count",
        "created_at",
        "modified_at",
    ]
    list_filter = ["created_at", "modified_at"]
    search_fields = ["title", "user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["id", "uuid", "created_at", "modified_at", "message_count"]
    raw_id_fields = ["user"]
    inlines = [ChatMessageInline]

    fieldsets = (
        (None, {"fields": ("user", "title")}),
        (
            "Statistics",
            {
                "fields": ("message_count",),
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

    def title_or_id(self, obj):
        return obj.title or f"Session {str(obj.uuid)[:8]}..."

    title_or_id.short_description = "Title"

    def message_count(self, obj):
        return obj.messages.count()

    message_count.short_description = "Messages"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = [
        "session_title",
        "short_uuid",
        "role",
        "content_preview",
        "attachment_count",
        "created_at",
    ]
    list_filter = ["role", "created_at"]
    search_fields = ["content", "session__title", "session__user__email"]
    readonly_fields = [
        "id",
        "uuid",
        "created_at",
        "modified_at",
        "attachments_preview",
    ]
    raw_id_fields = ["session"]

    fieldsets = (
        (None, {"fields": ("session", "role", "content")}),
        (
            "Attachments",
            {
                "fields": ("attachments_preview", "attachments"),
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

    def session_title(self, obj):
        return obj.session.title or f"Session {str(obj.session.uuid)[:8]}..."

    session_title.short_description = "Session"

    def content_preview(self, obj):
        if obj.content:
            preview = (
                obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
            )
            return format_html(
                '<div style="max-width: 400px; white-space: pre-wrap;">{}</div>',
                preview,
            )
        return "-"

    content_preview.short_description = "Content Preview"

    def attachment_count(self, obj):
        return len(obj.attachments or [])

    attachment_count.short_description = "Attachments"

    def attachments_preview(self, obj):
        """
        Render thumbnails for each attached asset by linking through the
        access-controlled serve view. Staff users can read any asset via
        that endpoint (see assets.views.serve_asset), so the admin
        always sees the bytes.
        """
        attachments = obj.attachments or []
        if not attachments:
            return "-"
        chunks = []
        for att in attachments:
            uuid = att.get("asset_uuid", "")
            if not uuid:
                continue
            url = f"/api/assets/{uuid}/"
            label = att.get("original_filename") or att.get("file_type") or uuid[:8]
            if att.get("file_type") == "image":
                chunks.append(
                    format_html(
                        '<a href="{}" target="_blank" rel="noopener" '
                        'style="margin-right: 0.4rem; display: inline-block;">'
                        '<img src="{}" style="max-width: 160px; max-height: 160px; '
                        'border: 1px solid #ccc; border-radius: 3px;" alt="{}" />'
                        "</a>",
                        url,
                        url,
                        label,
                    )
                )
            else:
                chunks.append(
                    format_html(
                        '<a href="{}" target="_blank" rel="noopener" '
                        'style="margin-right: 0.4rem;">▤ {}</a>',
                        url,
                        label,
                    )
                )
        # chunks is a list of SafeStrings produced by format_html; join
        # them and mark_safe so they aren't re-escaped on render.
        return mark_safe("".join(str(c) for c in chunks)) if chunks else "-"

    attachments_preview.short_description = "Preview"


@admin.register(UserAISettings)
class UserAISettingsAdmin(admin.ModelAdmin):
    list_display = ["user", "short_uuid", "preferred_model", "created_at"]
    list_filter = ["created_at", "preferred_model__provider"]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "preferred_model__name",
        "preferred_model__display_name",
    ]
    readonly_fields = ["id", "uuid", "created_at", "modified_at"]
    raw_id_fields = ["user", "preferred_model"]

    fieldsets = (
        (None, {"fields": ("user", "preferred_model")}),
        (
            "Metadata",
            {
                "fields": ("id", "uuid", "created_at", "modified_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(UserProviderConfig)
class UserProviderConfigAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "short_uuid",
        "provider",
        "is_enabled",
        "has_api_key",
        "enabled_models_count",
        "created_at",
    ]
    list_filter = ["provider", "is_enabled", "created_at"]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "provider__name",
    ]
    readonly_fields = ["id", "uuid", "created_at", "modified_at"]
    raw_id_fields = ["user", "provider"]

    fieldsets = (
        (None, {"fields": ("user", "provider", "is_enabled")}),
        (
            "API Configuration",
            {
                "fields": ("api_key",),
                "description": "API key is stored securely and masked in the admin interface.",
            },
        ),
        (
            "Model Configuration",
            {
                "fields": ("enabled_models",),
                "description": "Models that this user has enabled for this provider.",
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

    def has_api_key(self, obj):
        return bool(obj.api_key)

    has_api_key.boolean = True
    has_api_key.short_description = "Has API Key"

    def enabled_models_count(self, obj):
        return obj.enabled_models.count()

    enabled_models_count.short_description = "Enabled Models"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.api_key:
            form.base_fields["api_key"].widget.attrs[
                "placeholder"
            ] = "*** API Key Set ***"
        return form
