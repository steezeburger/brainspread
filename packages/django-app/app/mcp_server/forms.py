"""Forms for the MCP OAuth flow."""

from typing import Any
from urllib.parse import urlparse

from django import forms
from django.core.exceptions import ValidationError
from oauth2_provider.settings import oauth2_settings

from common.forms.base_form import BaseForm


class OAuthClientRegistrationForm(BaseForm):
    """Validates an RFC 7591 Dynamic Client Registration request.

    The MCP client POSTs its metadata (notably ``redirect_uris``) as
    JSON; we accept the subset we support for authorization-code +
    PKCE clients.
    """

    redirect_uris = forms.JSONField()
    client_name = forms.CharField(required=False, max_length=255)
    token_endpoint_auth_method = forms.CharField(required=False, max_length=64)
    grant_types = forms.JSONField(required=False)
    response_types = forms.JSONField(required=False)
    scope = forms.CharField(required=False, max_length=255)

    def clean_redirect_uris(self) -> list[str]:
        value: Any = self.cleaned_data.get("redirect_uris")
        if not isinstance(value, list) or not value:
            raise ValidationError("redirect_uris must be a non-empty array")
        allowed = {s.lower() for s in oauth2_settings.ALLOWED_REDIRECT_URI_SCHEMES}
        for uri in value:
            if not isinstance(uri, str) or not uri.strip():
                raise ValidationError("redirect_uris must be non-empty strings")
            scheme = urlparse(uri).scheme.lower()
            if scheme not in allowed:
                raise ValidationError(f"redirect_uri scheme '{scheme}' is not allowed")
        return value
