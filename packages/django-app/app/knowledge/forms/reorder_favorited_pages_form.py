import uuid as uuid_lib
from typing import List

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class ReorderFavoritedPagesForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page_uuids = forms.JSONField()

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_page_uuids(self) -> List[str]:
        raw = self.cleaned_data.get("page_uuids")

        if not isinstance(raw, list):
            raise ValidationError("page_uuids must be a list")

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
                raise ValidationError(f"Duplicate page UUID: {s}")
            seen.add(s)
            normalized.append(s)

        return normalized
