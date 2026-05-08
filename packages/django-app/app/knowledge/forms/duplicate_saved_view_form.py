from django import forms

from common.forms.user_form import UserForm


class DuplicateSavedViewForm(UserForm):
    """Clone an existing SavedView (system or user-owned) into a new
    user-owned view the caller can edit. ``new_name`` is optional — when
    omitted the cloned view picks up "<original> (copy)"."""

    view_uuid = forms.UUIDField()
    new_name = forms.CharField(max_length=200, required=False)
