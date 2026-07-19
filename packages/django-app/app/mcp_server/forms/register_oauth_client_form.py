from typing import Any, List
from urllib.parse import urlparse

from django import forms
from django.core.exceptions import ValidationError

from common.forms.base_form import BaseForm

# Loopback redirects stay plain http (RFC 8252 §7.3); anything else
# must be https so authorization codes never transit cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def _is_valid_redirect_uri(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.scheme == "https":
        return bool(parsed.netloc)
    if parsed.scheme == "http":
        return parsed.hostname in LOOPBACK_HOSTS
    return False


class RegisterOAuthClientForm(BaseForm):
    """Inputs for dynamic client registration (RFC 7591)."""

    client_name = forms.CharField(required=False, max_length=255)
    redirect_uris = forms.JSONField(required=True)

    def clean_redirect_uris(self) -> List[str]:
        uris: Any = self.cleaned_data.get("redirect_uris")
        if not isinstance(uris, list) or not uris:
            raise ValidationError("redirect_uris must be a non-empty array")
        for uri in uris:
            if not isinstance(uri, str) or not _is_valid_redirect_uri(uri):
                raise ValidationError(
                    f"invalid redirect_uri {uri!r}: must be https, or http on "
                    "localhost / 127.0.0.1"
                )
        return uris
