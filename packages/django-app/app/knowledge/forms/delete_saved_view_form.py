from django import forms

from common.forms.user_form import UserForm


class DeleteSavedViewForm(UserForm):
    """Delete a user-owned SavedView (system views can't be deleted)."""

    view_uuid = forms.UUIDField()
