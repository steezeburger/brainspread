from django import forms

from common.forms.user_form import UserForm


class PreviewSavedViewForm(UserForm):
    """Inputs for previewing an in-progress saved view spec without
    persisting it. Used by the editor's Run button so a user can see
    results for the spec they're currently typing, not the spec last
    saved on disk."""

    filter = forms.JSONField()
    sort = forms.JSONField(required=False)
    limit = forms.IntegerField(min_value=1, max_value=500, required=False, initial=100)

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
