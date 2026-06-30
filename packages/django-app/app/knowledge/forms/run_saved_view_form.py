from django import forms

from common.forms.user_form import UserForm


class RunSavedViewForm(UserForm):
    """Inputs for executing a saved view's filter and returning the matched blocks."""

    view_uuid = forms.UUIDField(required=False)
    view_slug = forms.SlugField(required=False, max_length=200)
    limit = forms.IntegerField(min_value=1, max_value=500, required=False, initial=100)
    # ISO YYYY-MM-DD. Only honored when the view has
    # ``dates_relative_to_daily=True``; otherwise the command ignores it
    # so a stray context_date can't shift a "live today" view.
    context_date = forms.DateField(required=False)
    # When true, return only the matched-block count (and truncation flag)
    # without serializing the rows. Collapsed embeds use this for their
    # header count — see RunSavedViewCommand.
    count_only = forms.BooleanField(required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("view_uuid") and not cleaned.get("view_slug"):
            raise forms.ValidationError("view_uuid or view_slug is required")
        if cleaned.get("view_uuid") and cleaned.get("view_slug"):
            raise forms.ValidationError("Pass view_uuid OR view_slug, not both")
        return cleaned
