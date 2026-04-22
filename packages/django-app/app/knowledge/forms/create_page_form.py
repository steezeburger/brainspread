from typing import Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Page


class CreatePageForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    title = forms.CharField(max_length=200, required=True)
    slug = forms.SlugField(max_length=200, required=False)
    is_published = forms.BooleanField(required=False, initial=True)
    page_type = forms.ChoiceField(
        choices=Page._meta.get_field("page_type").choices,
        required=False,
    )

    def clean_title(self) -> str:
        title = self.cleaned_data.get("title")
        if title:
            title = title.strip()
            if not title:
                raise ValidationError("Title cannot be empty")
        return title

    def clean_slug(self) -> Optional[str]:
        slug = self.cleaned_data.get("slug")
        user = self.cleaned_data.get("user")
        if slug and user:
            # Check if slug already exists for this user
            if Page.objects.filter(user=user, slug=slug).exists():
                raise ValidationError(f"Page with slug '{slug}' already exists")
        return slug

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
