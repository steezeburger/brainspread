from django import forms
from django.utils.text import slugify

from common.forms.user_form import UserForm


class CreateSavedViewForm(UserForm):
    """Create a user-owned SavedView.

    ``filter`` and ``sort`` arrive as JSON. They're validated for shape
    here (must parse as dict / list) and again at execute-time by the
    QueryEngine — predicate validity (unknown fields, bad ops) is the
    engine's job, not the form's. ``is_system`` is intentionally absent
    on the form: only the seed migration / register flow sets that.
    """

    name = forms.CharField(max_length=200)
    slug = forms.SlugField(max_length=200, required=False)
    description = forms.CharField(max_length=500, required=False)
    filter = forms.JSONField()
    sort = forms.JSONField(required=False)

    def clean_filter(self):
        v = self.cleaned_data.get("filter")
        if not isinstance(v, dict):
            raise forms.ValidationError("filter must be a JSON object")
        return v

    def clean_sort(self):
        v = self.cleaned_data.get("sort")
        if v is None:
            return []
        if not isinstance(v, list):
            raise forms.ValidationError("sort must be a JSON array")
        return v

    def clean(self):
        cleaned = super().clean()
        # Auto-slug from name if the caller didn't supply one — matches
        # the create-page flow's UX.
        if not cleaned.get("slug") and cleaned.get("name"):
            cleaned["slug"] = slugify(cleaned["name"])[:200]
        return cleaned
