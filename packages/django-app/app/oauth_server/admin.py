from django.contrib import admin

from .models import OAuthClient, OAuthToken


@admin.register(OAuthClient)
class OAuthClientAdmin(admin.ModelAdmin):
    list_display = ("client_name", "client_id", "created_at")
    search_fields = ("client_name", "client_id")
    readonly_fields = (
        "uuid",
        "client_id",
        "redirect_uris",
        "created_at",
        "modified_at",
    )

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(OAuthToken)
class OAuthTokenAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "user",
        "family_id",
        "created_at",
        "last_used_at",
        "access_expires_at",
        "replaced_at",
        "revoked_at",
    )
    list_filter = ("revoked_at",)
    search_fields = ("user__email", "client__client_name")
    # Inspect or revoke (set revoked_at) only; tokens come from the flow.
    readonly_fields = (
        "uuid",
        "user",
        "client",
        "family_id",
        "access_token_hash",
        "access_expires_at",
        "refresh_token_hash",
        "refresh_expires_at",
        "scope",
        "resource",
        "last_used_at",
        "replaced_at",
        "created_at",
        "modified_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
