from django import forms

from common.forms.base_form import BaseForm


class ExchangeAuthorizationCodeForm(BaseForm):
    code = forms.CharField(max_length=200)
    redirect_uri = forms.CharField(max_length=2000)
    client_id = forms.CharField(max_length=64)
    code_verifier = forms.RegexField(
        regex=r"^[A-Za-z0-9\-._~]{43,128}$",
        error_messages={"invalid": "code_verifier must be 43-128 unreserved chars"},
    )
    resource = forms.CharField(required=False, max_length=2000)


class RefreshOAuthTokenForm(BaseForm):
    refresh_token = forms.CharField(max_length=200)
    client_id = forms.CharField(max_length=64)
