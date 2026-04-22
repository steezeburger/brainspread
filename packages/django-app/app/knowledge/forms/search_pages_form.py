from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


class SearchPagesForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    query = forms.CharField(max_length=200, required=True)
    limit = forms.IntegerField(min_value=1, max_value=20, required=False, initial=10)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_query(self) -> str:
        query = self.cleaned_data.get("query", "").strip()
        if not query:
            raise ValidationError("Search query is required")
        return query
