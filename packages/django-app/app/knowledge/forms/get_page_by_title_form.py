from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetPageByTitleForm(BaseForm):
    """Inputs for the assistant's get_page_by_title tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    title = forms.CharField(min_length=1)
