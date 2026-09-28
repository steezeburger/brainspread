from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class SoftDeleteWebArchivesForBlocksForm(BaseForm):
    """
    Bulk soft-delete the archives tied to a set of blocks. Used by
    DeleteBlockCommand to clean up every archive in a deleted subtree in
    one shot — see WebArchiveRepository.soft_delete_for_blocks.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    block_uuids = forms.JSONField()

    def clean_block_uuids(self) -> List[str]:
        raw = self.cleaned_data.get("block_uuids")
        if not isinstance(raw, list) or not raw:
            raise ValidationError("block_uuids must be a non-empty list")
        return [str(uuid) for uuid in raw]

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user
