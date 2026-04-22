from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository


def _coerce_bool(raw, default: bool) -> bool:
    """Coerce a query-string style boolean value to a real bool.

    Django's forms.BooleanField treats any non-empty string as True, which
    means `"false"` is truthy. We want the common url-encoded semantics
    where `false`/`0`/`no`/`off` all map to False.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    return default


class GetGraphDataForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    include_daily = forms.CharField(required=False)
    include_orphans = forms.CharField(required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_include_daily(self) -> bool:
        return _coerce_bool(self.cleaned_data.get("include_daily"), default=False)

    def clean_include_orphans(self) -> bool:
        return _coerce_bool(self.cleaned_data.get("include_orphans"), default=True)
