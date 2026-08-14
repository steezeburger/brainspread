from django import forms
from django.core.exceptions import ValidationError

from common.forms.user_form import UserForm

from ..models.page_embedded_view import EMBED_COLOR_CHOICES


class UpdatePageEmbeddedViewForm(UserForm):
    """Toggle an embed's collapsed state, move it to a specific order,
    or set its accent color.

    All fields are optional so the same endpoint can serve "collapse
    this", "set this embed's order=2", and "make this red" without
    separate endpoints. ``color`` distinguishes absent (leave unchanged)
    from ``""`` (clear the accent) by checking submitted data in
    ``clean_color`` — a plain CharField can't tell those apart.
    """

    embed_uuid = forms.UUIDField()
    collapsed = forms.NullBooleanField(required=False)
    order = forms.IntegerField(min_value=0, required=False)
    color = forms.CharField(required=False)

    def clean_color(self) -> str | None:
        if "color" not in self.data:
            return None
        color = self.cleaned_data.get("color") or ""
        valid = {key for key, _ in EMBED_COLOR_CHOICES}
        if color not in valid:
            raise ValidationError(f"Unknown embed color '{color}'")
        return color
