from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import GetUserPreferencesForm


class GetUserPreferencesCommand(AbstractBaseCommand):
    """Return the user's display / app-level preferences for the
    assistant — the fields the chat surface itself respects (timezone,
    theme, etc). Secrets (api keys, full webhook URLs) are deliberately
    omitted; we only surface a boolean for whether the integration is
    configured.
    """

    def __init__(self, form: GetUserPreferencesForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]

        # Avoid eager imports at module load — UserAISettings lives in
        # ai_chat which would otherwise create a core <-> ai_chat cycle.
        from ai_chat.models import UserAISettings

        try:
            ai_settings = UserAISettings.objects.select_related("preferred_model").get(
                user=user
            )
            preferred_model_label = (
                ai_settings.preferred_model.display_name
                if ai_settings.preferred_model
                else None
            )
        except UserAISettings.DoesNotExist:
            preferred_model_label = None

        return {
            "timezone": user.timezone or "UTC",
            "theme": user.theme,
            "time_format": user.time_format,
            "has_discord_webhook": bool(user.discord_webhook_url),
            "has_discord_user_id": bool(user.discord_user_id),
            "preferred_model_label": preferred_model_label,
        }
