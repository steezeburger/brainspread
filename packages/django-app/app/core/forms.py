import pytz
from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.helpers import is_staging_theme_available
from core.repositories.user_repository import UserRepository


class LoginForm(BaseForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(required=True)
    timezone = forms.CharField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            user = authenticate(username=email, password=password)
            if not user or not user.is_active:
                raise ValidationError("Invalid credentials")
            cleaned_data["user"] = user

        return cleaned_data


class RegisterForm(BaseForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(required=True)

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if UserRepository.email_exists(email):
            raise ValidationError("User with this email already exists")
        return email


class UpdateTimezoneForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    timezone = forms.CharField(required=True)

    def clean_timezone(self):
        timezone = self.cleaned_data.get("timezone")
        try:
            pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError:
            pass
        return timezone


class UpdateThemeForm(BaseForm):
    BASE_THEME_CHOICES = [
        ("dark", "Dark"),
        ("light", "Light"),
        ("solarized_dark", "Solarized Dark"),
        ("purple", "Purple"),
        ("earthy", "Earthy"),
        ("forest", "Forest"),
    ]
    STAGING_THEME_CHOICE = ("staging", "Staging")

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    theme = forms.ChoiceField(choices=BASE_THEME_CHOICES, required=True)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Allow the staging theme as a valid submission only on
        # non-prod deploys. The choice is decided per-request so a
        # process restart isn't needed if ENVIRONMENT changes between
        # tests, but in practice the env is fixed for the lifetime of
        # the deploy.
        if is_staging_theme_available():
            self.fields["theme"].choices = self.BASE_THEME_CHOICES + [
                self.STAGING_THEME_CHOICE
            ]

    def clean_theme(self) -> str:
        theme = self.cleaned_data.get("theme")
        allowed = {choice[0] for choice in self.fields["theme"].choices}
        if theme not in allowed:
            raise ValidationError("Invalid theme choice")
        return theme


class UpdateTimeFormatForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    time_format = forms.ChoiceField(
        choices=[("24h", "24 hour"), ("12h", "12 hour")], required=True
    )


class UpdateDiscordWebhookForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    discord_webhook_url = forms.URLField(required=False, empty_value="", max_length=500)

    def clean_discord_webhook_url(self) -> str:
        url = self.cleaned_data.get("discord_webhook_url") or ""
        if url and not url.startswith("https://discord.com/api/webhooks/"):
            raise ValidationError(
                "Discord webhook URLs must start with "
                "'https://discord.com/api/webhooks/'"
            )
        return url


class UpdateDiscordUserIdForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    discord_user_id = forms.CharField(required=False, max_length=32, empty_value="")

    def clean_discord_user_id(self) -> str:
        value = (self.cleaned_data.get("discord_user_id") or "").strip()
        if value and not value.isdigit():
            raise ValidationError(
                "Discord user IDs are numeric. In Discord, enable Developer "
                "Mode then right-click your name → Copy User ID."
            )
        return value
