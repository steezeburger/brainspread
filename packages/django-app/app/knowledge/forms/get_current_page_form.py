from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import PageRepository


class GetCurrentPageForm(BaseForm):
    """Inputs for the assistant's get_current_page tool.

    The page uuid is supplied by the chat surface (the user's open
    page), not by the LLM — we just validate it belongs to the user.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)

    def clean_page(self):
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")
        if page and user and page.user_id != user.id:
            raise ValidationError("Page not found")
        return page
