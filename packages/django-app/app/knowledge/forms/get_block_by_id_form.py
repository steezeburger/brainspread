from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetBlockByIdForm(BaseForm):
    """Inputs for the assistant's get_block_by_id tool."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuid = forms.UUIDField()
