from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class ListScheduledBlocksForm(BaseForm):
    """Inputs for the assistant's list_scheduled_blocks tool.

    Dates are pre-resolved to ISO YYYY-MM-DD by the executor (which
    accepts LLM-friendly tokens like 'tomorrow' / '+7d') before reaching
    the form. The form just validates them as real dates.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    start_date = forms.DateField(required=False)
    end_date = forms.DateField(required=False)
    limit = forms.IntegerField(min_value=1, max_value=200, required=False, initial=50)
