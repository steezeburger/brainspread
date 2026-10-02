from django import forms

from common.forms.base_form import BaseForm

from ..helpers import is_valid_redirect_uri
from .fields import StringListField

SUPPORTED_GRANT_TYPES = {"authorization_code", "refresh_token"}
MAX_REDIRECT_URIS = 10


class RegisterOAuthClientForm(BaseForm):
    """RFC 7591 client metadata. Only what we act on is validated; any
    other metadata the client sends is ignored."""

    redirect_uris = StringListField()
    client_name = forms.CharField(required=False, max_length=200)
    grant_types = StringListField(required=False)
    response_types = StringListField(required=False)

    def clean_redirect_uris(self) -> list[str]:
        uris = self.cleaned_data["redirect_uris"]
        if not uris:
            raise forms.ValidationError("At least one redirect URI is required")
        if len(uris) > MAX_REDIRECT_URIS:
            raise forms.ValidationError("Too many redirect URIs")
        for uri in uris:
            if len(uri) > 2000 or not is_valid_redirect_uri(uri):
                raise forms.ValidationError(f"Invalid redirect URI: {uri}")
        return uris

    def clean_grant_types(self) -> list[str]:
        grant_types = self.cleaned_data.get("grant_types") or []
        unsupported = set(grant_types) - SUPPORTED_GRANT_TYPES
        if unsupported:
            raise forms.ValidationError(
                f"Unsupported grant types: {', '.join(sorted(unsupported))}"
            )
        return grant_types

    def clean_response_types(self) -> list[str]:
        response_types = self.cleaned_data.get("response_types") or []
        if set(response_types) - {"code"}:
            raise forms.ValidationError("Only the 'code' response type is supported")
        return response_types
