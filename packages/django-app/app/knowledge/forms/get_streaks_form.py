from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetStreaksForm(BaseForm):
    """Inputs for the assistant's get_streaks tool."""

    KIND_JOURNAL = "journal"
    KIND_COMPLETION = "completion"
    KIND_CHOICES = [
        (KIND_JOURNAL, "Journal"),
        (KIND_COMPLETION, "Completion"),
    ]

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    kind = forms.ChoiceField(choices=KIND_CHOICES)
    as_of = forms.DateField(required=False)
