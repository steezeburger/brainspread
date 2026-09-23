from django import forms

from common.forms.user_form import UserForm


class CreateCustomVariableForm(UserForm):
    """Define a ``{{name}}`` custom variable (issue #228). Name rules and
    the built-in / uniqueness / cycle checks live in the command."""

    name = forms.CharField(max_length=64)
    expansion = forms.CharField(strip=False)
