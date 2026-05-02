from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class SearchNotesForm(BaseForm):
    """Inputs for the assistant's search_notes tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    query = forms.CharField(min_length=1)
    limit = forms.IntegerField(min_value=1, max_value=25, required=False, initial=10)
