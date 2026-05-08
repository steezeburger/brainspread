from typing import Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Page


class DuplicatePageForm(BaseForm):
    """Clone a page (and its full block tree) into a new page owned by
    the same user. Powers both "Duplicate page" and "Save as template"
    actions — the caller picks the target page_type via ``new_page_type``.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    source_page_uuid = forms.UUIDField()
    new_title = forms.CharField(max_length=200, required=False)
    new_page_type = forms.ChoiceField(
        choices=Page._meta.get_field("page_type").choices,
        required=False,
    )

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_new_title(self) -> Optional[str]:
        title = self.cleaned_data.get("new_title")
        if title is not None:
            title = title.strip()
        return title or None
