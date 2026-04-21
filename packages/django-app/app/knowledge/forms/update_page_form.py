from typing import Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Page
from ..repositories import PageRepository


class UpdatePageForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)
    title = forms.CharField(max_length=200, required=False)
    content = forms.CharField(widget=forms.Textarea, required=False)
    is_published = forms.BooleanField(required=False)

    def clean_page(self) -> Page:
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")

        if page and user and page.user != user:
            raise ValidationError("Page not found")

        return page

    def clean_title(self) -> Optional[str]:
        # Distinguish "title omitted from payload" from "title explicitly blank".
        # Django's CharField(required=False) coerces a missing field to "", so
        # without this guard every partial update (e.g. whiteboard snapshot saves
        # that only send `content`) would trip the empty-title check.
        if "title" not in self.data:
            return None
        title = self.cleaned_data.get("title")
        if title is not None:
            title = title.strip()
            if not title:
                raise ValidationError("Title cannot be empty")
        return title

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
