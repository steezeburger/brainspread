from typing import Any, Dict

from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..services.query_dsl import QueryDSLError, compile_inline_query


class RunQueryForm(BaseForm):
    """Inputs for the run_query AI tool (issue #78).

    Exactly one of:
    - ``query`` — an inline DSL expression (``tag:x and type:todo``),
      compiled here so a bad expression is a validation error with the
      parser's own message, and ``cleaned_data['filter']`` always holds
      an engine-ready spec for the command;
    - ``filter`` — a raw query-engine filter dict, the escape hatch for
      shapes the DSL can't express (property ops, nested spec detail).
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    query = forms.CharField(required=False)
    filter = forms.JSONField(required=False)
    sort = forms.JSONField(required=False)
    limit = forms.IntegerField(required=False, min_value=1, max_value=100)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_filter(self) -> Any:
        spec = self.cleaned_data.get("filter")
        if spec is not None and not isinstance(spec, dict):
            raise ValidationError("filter must be a JSON object")
        return spec

    def clean_sort(self) -> Any:
        sort = self.cleaned_data.get("sort")
        if sort is not None and not isinstance(sort, list):
            raise ValidationError('sort must be a list of {"field", "dir"} objects')
        return sort

    def clean(self) -> Dict[str, Any]:
        cleaned_data = super().clean()
        query = (cleaned_data.get("query") or "").strip()
        filter_spec = cleaned_data.get("filter")

        if bool(query) == (filter_spec is not None):
            raise ValidationError(
                "Pass exactly one of `query` (DSL expression) or `filter` "
                "(query-engine JSON)"
            )

        if query:
            try:
                cleaned_data["filter"] = compile_inline_query(query)
            except QueryDSLError as exc:
                raise ValidationError(f"bad query: {exc}") from exc
        return cleaned_data
