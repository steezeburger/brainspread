from typing import Optional

from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository

from ..constants import MCP_SCOPE, SCOPES_SUPPORTED
from ..helpers import is_mcp_resource, redirect_uri_matches
from ..models import OAuthClient
from ..repositories import OAuthClientRepository

# Errors on these fields mean we can't trust redirect_uri, so the user
# sees an error page instead of being bounced back to the client.
UNREDIRECTABLE_FIELDS = ("client_id", "redirect_uri")


class AuthorizeRequestForm(BaseForm):
    """The parameters of an authorization request (RFC 6749 4.1.1 +
    PKCE). Used both to render the consent screen and to process its
    submission."""

    response_type = forms.CharField()
    client_id = forms.CharField(max_length=64)
    redirect_uri = forms.CharField(max_length=2000)
    code_challenge = forms.CharField(min_length=43, max_length=128)
    code_challenge_method = forms.CharField()
    state = forms.CharField(required=False, max_length=2000)
    scope = forms.CharField(required=False, max_length=200)
    resource = forms.CharField(required=False, max_length=2000)

    client: Optional[OAuthClient] = None

    def clean_client_id(self) -> str:
        client_id = self.cleaned_data["client_id"]
        self.client = OAuthClientRepository.get_by_client_id(client_id)
        if self.client is None:
            raise forms.ValidationError("Unknown client")
        return client_id

    def clean_redirect_uri(self) -> str:
        redirect_uri = self.cleaned_data["redirect_uri"]
        # clean_client_id runs first (field order), so self.client is set
        # whenever the client exists.
        if self.client and not redirect_uri_matches(
            redirect_uri, self.client.redirect_uris
        ):
            raise forms.ValidationError("Redirect URI isn't registered for this client")
        return redirect_uri

    def clean_response_type(self) -> str:
        response_type = self.cleaned_data["response_type"]
        if response_type != "code":
            raise forms.ValidationError("Only the 'code' response type is supported")
        return response_type

    def clean_code_challenge_method(self) -> str:
        method = self.cleaned_data["code_challenge_method"]
        if method != "S256":
            raise forms.ValidationError("code_challenge_method must be S256")
        return method

    def clean_scope(self) -> str:
        requested = (self.cleaned_data.get("scope") or "").split()
        unknown = set(requested) - set(SCOPES_SUPPORTED)
        if unknown:
            raise forms.ValidationError(f"Unknown scope: {' '.join(sorted(unknown))}")
        # Every token gets the MCP scope; offline_access is implied by the
        # refresh token we always issue.
        return MCP_SCOPE

    def clean_resource(self) -> str:
        resource = self.cleaned_data.get("resource") or ""
        if resource and not is_mcp_resource(resource):
            raise forms.ValidationError("Unknown resource")
        return resource

    @property
    def can_redirect(self) -> bool:
        return not any(field in self.errors for field in UNREDIRECTABLE_FIELDS)

    @property
    def redirect_error_code(self) -> str:
        """The RFC 6749 4.1.2.1 error code for a redirectable failure."""
        if "response_type" in self.errors:
            return "unsupported_response_type"
        if "scope" in self.errors:
            return "invalid_scope"
        if "resource" in self.errors:
            return "invalid_target"
        return "invalid_request"


class ApproveAuthorizationForm(AuthorizeRequestForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
