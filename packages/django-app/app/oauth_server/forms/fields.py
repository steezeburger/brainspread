from typing import Any

from django import forms


class StringListField(forms.Field):
    """A JSON array of strings, as RFC 7591 registration requests carry."""

    def to_python(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise forms.ValidationError("Must be a list of strings")
        return value
