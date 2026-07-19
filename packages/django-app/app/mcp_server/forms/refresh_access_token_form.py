from django import forms

from common.forms.base_form import BaseForm


class RefreshAccessTokenForm(BaseForm):
    """Token-endpoint inputs for grant_type=refresh_token."""

    refresh_token = forms.CharField(required=True, max_length=128)
    client_id = forms.CharField(required=True)
    resource = forms.CharField(required=False, max_length=1024)
