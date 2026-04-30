from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Page
from ..repositories import PageRepository


class TouchPageForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)

    def clean_page(self) -> Page:
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")

        if page and user and page.user != user:
            raise ValidationError("Page not found")

        return page

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
