from django import forms

from common.forms.user_form import UserForm


class ListOAuthConnectionsForm(UserForm):
    pass


class RevokeOAuthConnectionForm(UserForm):
    family_id = forms.UUIDField()
