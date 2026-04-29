from django import forms

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class GetAssetForm(BaseForm):
    """Resolve an asset for a user by uuid (used by the serve endpoint)."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    uuid = forms.UUIDField()

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise forms.ValidationError("User is required")
        return user
