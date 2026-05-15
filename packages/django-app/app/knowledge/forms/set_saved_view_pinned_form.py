from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import SavedView
from ..repositories import SavedViewRepository


class SetSavedViewPinnedForm(BaseForm):
    """Toggle a saved view's pinned flag — surface or hide it in the left nav."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    view = UUIDModelChoiceField(
        queryset=SavedViewRepository.get_queryset(), required=True
    )
    pinned = forms.BooleanField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_view(self) -> SavedView:
        view = self.cleaned_data.get("view")
        user = self.cleaned_data.get("user")
        if view and user and view.user_id != user.id:
            raise ValidationError("View not found")
        return view
