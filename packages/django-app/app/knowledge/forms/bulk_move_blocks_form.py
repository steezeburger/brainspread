import uuid as uuid_lib
from typing import List, Optional

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class BulkMoveBlocksForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    blocks = forms.JSONField()
    target_date = forms.DateField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_blocks(self) -> List[str]:
        raw = self.cleaned_data.get("blocks")

        if not isinstance(raw, list):
            raise ValidationError("blocks must be a list")
        if not raw:
            raise ValidationError("blocks list must not be empty")

        normalized: List[str] = []
        seen = set()
        for i, item in enumerate(raw):
            try:
                parsed = uuid_lib.UUID(str(item))
            except (ValueError, AttributeError, TypeError):
                raise ValidationError(
                    f"Item at index {i} has an invalid UUID: {item!r}"
                )
            s = str(parsed)
            if s in seen:
                continue
            seen.add(s)
            normalized.append(s)

        return normalized

    def clean_target_date(self) -> Optional[object]:
        return self.cleaned_data.get("target_date")
