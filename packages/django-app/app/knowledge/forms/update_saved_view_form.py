from django import forms

from common.forms.user_form import UserForm


class UpdateSavedViewForm(UserForm):
    """Edit a user-owned SavedView. The view's UUID is required; every
    other field is optional and only fields actually submitted are
    applied (BaseForm filters cleaned_data to submitted keys)."""

    view_uuid = forms.UUIDField()
    name = forms.CharField(max_length=200, required=False)
    slug = forms.SlugField(max_length=200, required=False)
    description = forms.CharField(max_length=500, required=False)
    filter = forms.JSONField(required=False)
    sort = forms.JSONField(required=False)

    def clean_filter(self):
        v = self.cleaned_data.get("filter")
        if v is None:
            return v
        if not isinstance(v, dict):
            raise forms.ValidationError("filter must be a JSON object")
        return v

    def clean_sort(self):
        v = self.cleaned_data.get("sort")
        if v is None:
            return v
        if not isinstance(v, list):
            raise forms.ValidationError("sort must be a JSON array")
        return v
