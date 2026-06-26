"""HTTP views for OAuth discovery, dynamic registration, and login.

These are the MCP-spec endpoints django-oauth-toolkit doesn't ship:
the two ``.well-known`` discovery documents, the RFC 7591 registration
endpoint, and a server-rendered login form (the app otherwise only has
SPA/API login, but the ``/o/authorize/`` step needs an in-browser
session).
"""

import json
from typing import Any

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .commands import RegisterOAuthClientCommand
from .forms import OAuthClientRegistrationForm
from .oauth_metadata import (
    authorization_server_metadata,
    protected_resource_metadata,
)


def _public_json(data: dict[str, Any], *, status: int = 200) -> JsonResponse:
    """JSON response with permissive CORS — these are public discovery docs."""
    response = JsonResponse(data, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@require_http_methods(["GET", "OPTIONS"])
def authorization_server_metadata_view(request: HttpRequest) -> JsonResponse:
    if request.method == "OPTIONS":
        return _public_json({})
    return _public_json(authorization_server_metadata(request))


@require_http_methods(["GET", "OPTIONS"])
def protected_resource_metadata_view(request: HttpRequest) -> JsonResponse:
    if request.method == "OPTIONS":
        return _public_json({})
    return _public_json(protected_resource_metadata(request))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def register_view(request: HttpRequest) -> JsonResponse:
    if request.method == "OPTIONS":
        return _public_json({})

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _public_json(
            {
                "error": "invalid_client_metadata",
                "error_description": "Request body must be JSON",
            },
            status=400,
        )
    if not isinstance(payload, dict):
        return _public_json(
            {
                "error": "invalid_client_metadata",
                "error_description": "Request body must be a JSON object",
            },
            status=400,
        )

    form = OAuthClientRegistrationForm(payload)
    if not form.is_valid():
        return _public_json(
            {
                "error": "invalid_client_metadata",
                "error_description": form.errors.as_text(),
            },
            status=400,
        )

    try:
        result = RegisterOAuthClientCommand(form).execute()
    except ValidationError as e:
        return _public_json(
            {"error": "invalid_client_metadata", "error_description": str(e)},
            status=400,
        )
    return _public_json(result, status=201)


class EmailLoginForm(AuthenticationForm):
    """AuthenticationForm relabeled for the email-as-username User model."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update(
            {"type": "email", "autofocus": True, "autocomplete": "email"}
        )
