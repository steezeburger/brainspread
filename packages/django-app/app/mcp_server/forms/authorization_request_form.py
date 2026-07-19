from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm
from mcp_server.constants import CODE_CHALLENGE_METHOD
from mcp_server.repositories import OAuthClientRepository


class AuthorizationRequestForm(BaseForm):
    """Validates the query parameters of an authorization request.

    Used on both the GET (render consent page) and POST (approve)
    sides of ``/oauth/authorize``. OAuth 2.1 makes PKCE mandatory, so
    a missing or non-S256 challenge is rejected outright.
    """

    client_id = forms.CharField(required=True)
    redirect_uri = forms.CharField(required=True)
    response_type = forms.CharField(required=True)
    code_challenge = forms.CharField(required=True, max_length=128)
    code_challenge_method = forms.CharField(required=False)
    state = forms.CharField(required=False, max_length=1024)
    # Sent by RFC 8707-aware clients; accepted but unused since this
    # server only protects a single resource.
    scope = forms.CharField(required=False, max_length=1024)
    resource = forms.CharField(required=False, max_length=1024)

    def clean(self) -> dict:
        cleaned_data = super().clean()

        client_id = cleaned_data.get("client_id")
        if client_id:
            client = OAuthClientRepository.get_by_client_id(client_id)
            if client is None:
                raise ValidationError("unknown client_id")
            cleaned_data["client"] = client

            redirect_uri = cleaned_data.get("redirect_uri")
            if redirect_uri and not client.is_registered_redirect_uri(redirect_uri):
                raise ValidationError("redirect_uri is not registered for this client")

        if cleaned_data.get("response_type") not in (None, "code"):
            raise ValidationError("only response_type=code is supported")

        method = cleaned_data.get("code_challenge_method") or CODE_CHALLENGE_METHOD
        if method != CODE_CHALLENGE_METHOD:
            raise ValidationError("only code_challenge_method=S256 is supported")
        cleaned_data["code_challenge_method"] = method

        return cleaned_data
