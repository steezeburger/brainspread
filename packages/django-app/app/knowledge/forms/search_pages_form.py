from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Page


class SearchPagesForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    query = forms.CharField(max_length=200, required=True)
    limit = forms.IntegerField(min_value=1, max_value=20, required=False, initial=10)
    # Optional constraint to a single page_type — used by callers that
    # only want certain shapes (e.g. the "add from template" picker
    # filters to page_type=template). Validated against Page's choices
    # so a typo returns a 400 instead of silently matching nothing.
    page_type = forms.ChoiceField(
        choices=Page._meta.get_field("page_type").choices,
        required=False,
    )

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
