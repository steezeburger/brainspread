from django import forms

from common.forms.user_form import UserForm


class GetSavedViewForm(UserForm):
    """Look up one of the user's views, by uuid or slug. Exactly one of
    the two must be provided; the form rejects both-or-neither."""

    view_uuid = forms.UUIDField(required=False)
    view_slug = forms.SlugField(required=False, max_length=200)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("view_uuid") and not cleaned.get("view_slug"):
            raise forms.ValidationError("view_uuid or view_slug is required")
        if cleaned.get("view_uuid") and cleaned.get("view_slug"):
            raise forms.ValidationError("Pass view_uuid OR view_slug, not both")
        return cleaned
