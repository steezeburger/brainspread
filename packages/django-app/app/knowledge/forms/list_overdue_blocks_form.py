from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class ListOverdueBlocksForm(BaseForm):
    """Inputs for the assistant's list_overdue_blocks tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    limit = forms.IntegerField(min_value=1, max_value=100, required=False, initial=25)
