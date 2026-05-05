from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetRecentActivityForm(BaseForm):
    """Inputs for the assistant's get_recent_activity tool."""

    KIND_BLOCK = "block"
    KIND_PAGE = "page"
    KIND_BOTH = "both"
    KIND_CHOICES = [
        (KIND_BLOCK, "Block"),
        (KIND_PAGE, "Page"),
        (KIND_BOTH, "Both"),
    ]

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    kind = forms.ChoiceField(choices=KIND_CHOICES, required=False, initial=KIND_BOTH)
    limit = forms.IntegerField(min_value=1, max_value=100, required=False, initial=20)
