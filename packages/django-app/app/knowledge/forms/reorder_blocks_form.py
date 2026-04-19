import uuid

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm
from core.models import User
from core.repositories import UserRepository


class ReorderBlocksForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    blocks = forms.JSONField()

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_blocks(self) -> list:
        blocks = self.cleaned_data.get("blocks")

        if not isinstance(blocks, list):
            raise ValidationError("blocks must be a list")

        if len(blocks) == 0:
            raise ValidationError("blocks list must not be empty")

        for i, item in enumerate(blocks):
            if not isinstance(item, dict):
                raise ValidationError(f"Item at index {i} must be an object")

            if "uuid" not in item:
                raise ValidationError(f"Item at index {i} is missing 'uuid'")

            if "order" not in item:
                raise ValidationError(f"Item at index {i} is missing 'order'")

            try:
                uuid.UUID(str(item["uuid"]))
            except (ValueError, AttributeError):
                raise ValidationError(
                    f"Item at index {i} has an invalid UUID: {item['uuid']!r}"
                )

            if not isinstance(item["order"], int) or item["order"] < 0:
                raise ValidationError(
                    f"Item at index {i} 'order' must be a non-negative integer"
                )

        return blocks
