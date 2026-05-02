from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetCompletionStatsForm(BaseForm):
    """Inputs for the assistant's get_completion_stats tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    start_date = forms.DateField()
    end_date = forms.DateField()
