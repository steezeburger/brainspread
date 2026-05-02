from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class FindStaleTodosForm(BaseForm):
    """Inputs for the assistant's find_stale_todos tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    older_than_days = forms.IntegerField(
        min_value=1, max_value=365, required=False, initial=14
    )
    limit = forms.IntegerField(min_value=1, max_value=200, required=False, initial=50)
