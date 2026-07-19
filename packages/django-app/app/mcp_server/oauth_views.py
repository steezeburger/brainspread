"""OAuth 2.1 endpoints for the MCP server.

Implements the minimum surface a remote MCP client (Claude Desktop /
claude.ai custom connectors) needs to connect without a hand-copied
token:

- RFC 8414 authorization-server metadata
- RFC 9728 protected-resource metadata
- RFC 7591 dynamic client registration (public clients only)
- authorization-code flow with mandatory PKCE (S256)
- token endpoint with refresh-token rotation

These are plain Django views, not DRF: the token and registration
endpoints are called by external OAuth clients that send form-encoded
or JSON bodies without CSRF tokens, and the authorize endpoint renders
HTML. Views only translate HTTP <-> forms/commands per the project's
command pattern.
"""

import json
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.contrib.auth import login as django_login
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.forms import LoginForm
from mcp_server.commands import (
    CreateAuthorizationCodeCommand,
    ExchangeAuthorizationCodeCommand,
    RefreshAccessTokenCommand,
    RegisterOAuthClientCommand,
)
from mcp_server.exceptions import OAuthError
from mcp_server.forms import (
    AuthorizationRequestForm,
    CreateAuthorizationCodeForm,
    ExchangeAuthorizationCodeForm,
    RefreshAccessTokenForm,
    RegisterOAuthClientForm,
)

logger = logging.getLogger(__name__)

GRANT_TYPES = ["authorization_code", "refresh_token"]

# Query params re-emitted as hidden fields on the consent form so the
# POST carries the full authorization request back to us.
AUTHORIZATION_REQUEST_PARAMS = [
    "client_id",
    "redirect_uri",
    "response_type",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
]


def _issuer(request: HttpRequest) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def _append_query_params(uri: str, params: Dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = parts.query + ("&" if parts.query else "") + urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _oauth_error_response(
    error: str, description: str, http_status: int = 400
) -> JsonResponse:
    response = JsonResponse(
        {"error": error, "error_description": description}, status=http_status
    )
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def authorization_server_metadata(
    request: HttpRequest, suffix: Optional[str] = None
) -> JsonResponse:
    """RFC 8414 metadata. ``suffix`` swallows path-suffixed discovery
    requests some clients issue (/.well-known/...-server/api/mcp)."""
    issuer = _issuer(request)
    return JsonResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": GRANT_TYPES,
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [],
        }
    )


@require_GET
def protected_resource_metadata(
    request: HttpRequest, suffix: Optional[str] = None
) -> JsonResponse:
    """RFC 9728 metadata pointing MCP clients at the authorization server."""
    issuer = _issuer(request)
    return JsonResponse(
        {
            "resource": f"{issuer}/api/mcp/",
            "resource_name": "brainspread MCP server",
            "authorization_servers": [issuer],
            "bearer_methods_supported": ["header"],
        }
    )


@csrf_exempt
@require_POST
def register_client(request: HttpRequest) -> JsonResponse:
    """RFC 7591 dynamic client registration (open, public clients only).

    Registration is unauthenticated by design: a client_id alone grants
    nothing — every token still requires a logged-in user to approve
    the PKCE authorization-code flow.
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _oauth_error_response("invalid_client_metadata", "malformed JSON body")
    if not isinstance(body, dict):
        return _oauth_error_response(
            "invalid_client_metadata", "request body must be a JSON object"
        )

    form = RegisterOAuthClientForm(body)
    if not form.is_valid():
        return _oauth_error_response(
            (
                "invalid_redirect_uri"
                if "redirect_uris" in form.errors
                else "invalid_client_metadata"
            ),
            form.errors.as_json(),
        )

    client = RegisterOAuthClientCommand(form).execute()
    return JsonResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": GRANT_TYPES,
            "response_types": ["code"],
        },
        status=201,
    )


def authorize(request: HttpRequest) -> HttpResponse:
    """Authorization endpoint: consent page on GET, decision on POST.

    A user with a live web-app session just approves; otherwise the
    consent page includes email/password fields and we authenticate
    inline (also starting a session so later authorizations skip it).
    """
    params = request.POST if request.method == "POST" else request.GET
    form = AuthorizationRequestForm(params)
    if not form.is_valid():
        # Per RFC 6749 §4.1.2.1 never redirect when the client or
        # redirect_uri can't be trusted — render the error instead.
        return render(
            request,
            "mcp_server/authorize_error.html",
            {"errors": form.errors.get("__all__") or ["invalid authorization request"]},
            status=400,
        )

    data = form.cleaned_data
    if request.method != "POST":
        return _render_consent_page(request, data)

    redirect_params: Dict[str, str] = {}
    state = data.get("state")
    if state:
        redirect_params["state"] = state

    if request.POST.get("action") != "approve":
        redirect_params["error"] = "access_denied"
        return _redirect_to_client(data["redirect_uri"], redirect_params)

    user = request.user if request.user.is_authenticated else None
    if user is None:
        login_form = LoginForm(
            {
                "email": request.POST.get("email", ""),
                "password": request.POST.get("password", ""),
            }
        )
        try:
            if not login_form.is_valid():
                return _render_consent_page(
                    request, data, login_error="invalid email or password"
                )
        except ValidationError:
            return _render_consent_page(
                request, data, login_error="invalid email or password"
            )
        user = login_form.cleaned_data["user"]
        django_login(request, user)

    code_form = CreateAuthorizationCodeForm(
        {
            **{key: data.get(key) or "" for key in AUTHORIZATION_REQUEST_PARAMS},
            "user": user.pk,
        }
    )
    auth_code = CreateAuthorizationCodeCommand(code_form).execute()
    redirect_params["code"] = auth_code.code
    return _redirect_to_client(data["redirect_uri"], redirect_params)


def _render_consent_page(
    request: HttpRequest,
    data: Dict[str, Any],
    login_error: Optional[str] = None,
) -> HttpResponse:
    hidden_fields = {
        key: data.get(key) or ""
        for key in AUTHORIZATION_REQUEST_PARAMS
        if data.get(key)
    }
    return render(
        request,
        "mcp_server/authorize.html",
        {
            "client_name": data["client"].client_name,
            "hidden_fields": hidden_fields,
            "needs_login": not request.user.is_authenticated,
            "login_error": login_error,
            "user_email": getattr(request.user, "email", ""),
        },
        status=200 if login_error is None else 401,
    )


def _redirect_to_client(redirect_uri: str, params: Dict[str, str]) -> HttpResponse:
    # Manual 302 instead of django.shortcuts.redirect: the target is an
    # external client-controlled URL that was validated against the
    # client's registered redirect_uris.
    response = HttpResponse(status=302)
    response["Location"] = _append_query_params(redirect_uri, params)
    return response


@csrf_exempt
@require_POST
def token(request: HttpRequest) -> JsonResponse:
    """Token endpoint: authorization_code exchange and refresh_token
    rotation. Accepts form-encoded bodies (what OAuth clients send)
    and JSON."""
    if request.content_type and "json" in request.content_type:
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return _oauth_error_response("invalid_request", "malformed JSON body")
        if not isinstance(payload, dict):
            return _oauth_error_response(
                "invalid_request", "request body must be a JSON object"
            )
    else:
        payload = request.POST

    grant_type = payload.get("grant_type")
    if grant_type == "authorization_code":
        form: Any = ExchangeAuthorizationCodeForm(payload)
        command_class: Any = ExchangeAuthorizationCodeCommand
    elif grant_type == "refresh_token":
        form = RefreshAccessTokenForm(payload)
        command_class = RefreshAccessTokenCommand
    else:
        return _oauth_error_response(
            "unsupported_grant_type",
            f"unsupported grant_type {grant_type!r}",
        )

    try:
        result = command_class(form).execute()
    except ValidationError as e:
        return _oauth_error_response("invalid_request", str(e))
    except OAuthError as e:
        return _oauth_error_response(
            e.error,
            e.description,
            http_status=401 if e.error == "invalid_client" else 400,
        )

    response = JsonResponse(
        {
            "access_token": result.token.access_token,
            "token_type": "Bearer",
            "expires_in": result.expires_in,
            "refresh_token": result.token.refresh_token,
            "scope": "",
        }
    )
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response
