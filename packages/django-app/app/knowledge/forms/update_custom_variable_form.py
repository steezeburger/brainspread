from django import forms

from common.forms.user_form import UserForm


class UpdateCustomVariableForm(UserForm):
    """Edit a custom variable. Only submitted fields are applied
    (BaseForm prunes cleaned_data to submitted keys)."""

    variable_uuid = forms.UUIDField()
    name = forms.CharField(max_length=64, required=False)
    expansion = forms.CharField(strip=False, required=False)
