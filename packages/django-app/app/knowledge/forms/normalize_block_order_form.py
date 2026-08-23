from django import forms

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm
from core.repositories import UserRepository

from ..models import Page
from ..repositories import PageRepository


class NormalizeBlockOrderForm(BaseForm):
    """Inputs for the block-order repair: one page, owned by the user."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)

    def clean_page(self) -> Page:
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")
        if page and user and page.user != user:
            raise forms.ValidationError("Page does not belong to the specified user")
        return page
