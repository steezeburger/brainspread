from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetTagGraphForm(BaseForm):
    """Inputs for the assistant's get_tag_graph tool — page co-occurrence
    via the Block.pages M2M tag relation."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    min_shared = forms.IntegerField(
        min_value=1, max_value=100, required=False, initial=2
    )
    limit = forms.IntegerField(min_value=1, max_value=200, required=False, initial=30)
