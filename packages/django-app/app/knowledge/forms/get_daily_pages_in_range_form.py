from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetDailyPagesInRangeForm(BaseForm):
    """Inputs for the assistant's get_daily_pages_in_range tool.

    Dates are pre-resolved to ISO by the executor before reaching the form.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    start_date = forms.DateField()
    end_date = forms.DateField()
