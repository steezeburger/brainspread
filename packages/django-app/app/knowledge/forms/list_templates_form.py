from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class ListTemplatesForm(BaseForm):
    """List the user's template pages (page_type='template')."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
