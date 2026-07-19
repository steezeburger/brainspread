from django import forms

from common.forms.base_form import BaseForm


class ExchangeAuthorizationCodeForm(BaseForm):
    """Token-endpoint inputs for grant_type=authorization_code.

    Shape-only validation; semantic checks (code validity, PKCE
    verification) live in ExchangeAuthorizationCodeCommand so they can
    raise precise OAuth error codes.
    """

    code = forms.CharField(required=True, max_length=128)
    client_id = forms.CharField(required=True)
    redirect_uri = forms.CharField(required=True)
    code_verifier = forms.CharField(required=True, min_length=43, max_length=128)
    resource = forms.CharField(required=False, max_length=1024)
