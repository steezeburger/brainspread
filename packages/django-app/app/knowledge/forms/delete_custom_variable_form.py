from django import forms

from common.forms.user_form import UserForm


class DeleteCustomVariableForm(UserForm):
    variable_uuid = forms.UUIDField()
