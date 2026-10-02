"""OAuth 2.1 authorization server for the MCP endpoint.

Lets Claude (claude.ai, Desktop, mobile, Claude Code) connect to
``/api/mcp/`` as a custom connector: discovery metadata (RFC 9728 +
RFC 8414), Dynamic Client Registration (RFC 7591), the authorization
code flow with PKCE, and rotating refresh tokens. Users sign in with
their normal brainspread account and approve each app on a consent
screen; connected apps are listed and revocable in settings.
"""

import json
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.exceptions import ValidationError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.forms import LoginForm

from .commands import (
    CreateAuthorizationCodeCommand,
    ExchangeAuthorizationCodeCommand,
    ListOAuthConnectionsCommand,
    RefreshOAuthTokenCommand,
    RegisterOAuthClientCommand,
    RevokeOAuthConnectionCommand,
)
from .constants import MCP_SCOPE, SCOPES_SUPPORTED
from .errors import OAuthError
from .forms import (
    ApproveAuthorizationForm,
    AuthorizeRequestForm,
    ExchangeAuthorizationCodeForm,
    ListOAuthConnectionsForm,
    RefreshOAuthTokenForm,
    RegisterOAuthClientForm,
    RevokeOAuthConnectionForm,
)
from .services.urls import add_query_params, is_loopback_redirect, issuer_url

# The resource paths a protected-resource metadata URL may be suffixed
# with: "" is the bare well-known path, the others mirror the MCP URL.
PROTECTED_RESOURCE_SUFFIXES = {
    "": "/api/mcp/",
    "api/mcp/": "/api/mcp/",
    "api/mcp": "/api/mcp",
}

# The query parameters an authorization request carries through login
# and the consent form.
AUTHORIZE_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


# --- discovery -----------------------------------------------------------


@require_GET
def protected_resource_metadata(request: HttpRequest, resource_path: str = ""):
    """RFC 9728. ``resource`` must equal the MCP URL the user typed, so
    the path-suffixed variant echoes the suffix back."""
    if resource_path not in PROTECTED_RESOURCE_SUFFIXES:
        raise Http404
    issuer = issuer_url(request)
    return JsonResponse(
        {
            "resource": issuer + PROTECTED_RESOURCE_SUFFIXES[resource_path],
            "authorization_servers": [issuer],
            "scopes_supported": [MCP_SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "brainspread",
        }
    )


@require_GET
def authorization_server_metadata(request: HttpRequest):
    """RFC 8414."""
    issuer = issuer_url(request)
    return JsonResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": issuer + reverse("oauth_server:authorize"),
            "token_endpoint": issuer + reverse("oauth_server:token"),
            "registration_endpoint": issuer + reverse("oauth_server:register"),
            "scopes_supported": SCOPES_SUPPORTED,
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
        }
    )


# --- registration --------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def register_client(request: HttpRequest):
    """RFC 7591 Dynamic Client Registration. Clients are always public:
    whatever auth method is asked for, ``none`` is what's registered."""
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _registration_error("invalid_client_metadata", "Body must be JSON")
    if not isinstance(body, dict):
        return _registration_error("invalid_client_metadata", "Body must be an object")

    form = RegisterOAuthClientForm(body)
    if not form.is_valid():
        code = (
            "invalid_redirect_uri"
            if "redirect_uris" in form.errors
            else "invalid_client_metadata"
        )
        return _registration_error(code, _first_error(form))

    client = RegisterOAuthClientCommand(form).execute()
    return JsonResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status=201,
    )


def _registration_error(error: str, description: str) -> JsonResponse:
    return JsonResponse({"error": error, "error_description": description}, status=400)


# --- authorization -------------------------------------------------------


@never_cache
@require_http_methods(["GET", "POST"])
def authorize(request: HttpRequest):
    """Consent screen. GET shows it; POST records the decision and sends
    the browser back to the client with a code (or an error)."""
    params = request.GET if request.method == "GET" else request.POST
    form = AuthorizeRequestForm(_authorize_params(params))
    if not form.is_valid() and not form.can_redirect:
        return _render_error(
            request,
            "This sign-in link isn't valid",
            "The app that sent you here sent an unknown client or redirect "
            "address. Try connecting again from the app.",
        )
    if form.errors:
        return _redirect_with_error(form, form.redirect_error_code, _first_error(form))

    if not request.user.is_authenticated:
        login_url = reverse("oauth_server:login")
        next_url = f"{reverse('oauth_server:authorize')}?{urlencode(_authorize_params(params))}"
        return redirect(f"{login_url}?{urlencode({'next': next_url})}")

    if request.method == "GET":
        redirect_uri = form.cleaned_data["redirect_uri"]
        return render(
            request,
            "oauth_server/authorize.html",
            {
                "client_name": form.client.display_name,
                "redirect_host": urlsplit(redirect_uri).hostname,
                "is_loopback": is_loopback_redirect(redirect_uri),
                "user_email": request.user.email,
                "params": _authorize_params(params),
                "switch_url": f"{reverse('oauth_server:login')}?"
                + urlencode(
                    {
                        "next": f"{reverse('oauth_server:authorize')}?"
                        + urlencode(_authorize_params(params))
                    }
                ),
            },
        )

    if request.POST.get("decision") != "allow":
        return _redirect_with_error(form, "access_denied", "The user denied access")

    approve_form = ApproveAuthorizationForm(
        {**_authorize_params(params), "user": request.user.id}
    )
    if not approve_form.is_valid():
        return _redirect_with_error(form, "invalid_request", _first_error(approve_form))
    code = CreateAuthorizationCodeCommand(approve_form).execute()
    return HttpResponseRedirect(
        add_query_params(
            form.cleaned_data["redirect_uri"],
            {
                "code": code,
                "state": form.cleaned_data.get("state"),
                "iss": issuer_url(request),
            },
        )
    )


def _authorize_params(params) -> dict[str, str]:
    return {key: params[key] for key in AUTHORIZE_PARAMS if params.get(key)}


def _redirect_with_error(
    form: AuthorizeRequestForm, error: str, description: str
) -> HttpResponseRedirect:
    return HttpResponseRedirect(
        add_query_params(
            form.cleaned_data["redirect_uri"],
            {
                "error": error,
                "error_description": description,
                "state": form.cleaned_data.get("state"),
            },
        )
    )


@never_cache
@require_http_methods(["GET", "POST"])
def login(request: HttpRequest):
    """Sign-in page for the OAuth flow. Only ever continues to the
    authorize endpoint, so it can't be used as an open redirect."""
    next_url = _safe_next(request.GET.get("next") or request.POST.get("next"))
    if next_url is None:
        return _render_error(
            request,
            "Nothing to sign in to",
            "Start from the app you're connecting to brainspread.",
        )

    if request.method == "POST" and request.POST.get("action") == "switch":
        django_logout(request)
        return redirect(
            f"{reverse('oauth_server:login')}?{urlencode({'next': next_url})}"
        )

    if request.user.is_authenticated:
        return redirect(next_url)

    error = ""
    email = ""
    if request.method == "POST":
        email = request.POST.get("email", "")
        form = LoginForm({"email": email, "password": request.POST.get("password", "")})
        if form.is_valid():
            django_login(request, form.cleaned_data["user"])
            return redirect(next_url)
        error = "Wrong email or password."

    return render(
        request,
        "oauth_server/login.html",
        {"next": next_url, "email": email, "error": error},
    )


def _safe_next(next_url: Optional[str]) -> Optional[str]:
    if not next_url:
        return None
    parts = urlsplit(next_url)
    if parts.scheme or parts.netloc or parts.path != reverse("oauth_server:authorize"):
        return None
    return next_url


def _render_error(request: HttpRequest, title: str, message: str) -> HttpResponse:
    return render(
        request,
        "oauth_server/error.html",
        {"title": title, "message": message},
        status=400,
    )


# --- token ---------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def token(request: HttpRequest):
    """RFC 6749 token endpoint (form-encoded, public clients + PKCE)."""
    grant_type = request.POST.get("grant_type")
    if grant_type == "authorization_code":
        form_class, command_class = (
            ExchangeAuthorizationCodeForm,
            ExchangeAuthorizationCodeCommand,
        )
    elif grant_type == "refresh_token":
        form_class, command_class = RefreshOAuthTokenForm, RefreshOAuthTokenCommand
    else:
        return _token_error(OAuthError("unsupported_grant_type"))

    form = form_class(request.POST.dict())
    if not form.is_valid():
        return _token_error(OAuthError("invalid_request", _first_error(form)))
    try:
        body = command_class(form).execute()
    except OAuthError as e:
        return _token_error(e)
    return _no_store(JsonResponse(body))


def _token_error(error: OAuthError) -> JsonResponse:
    return _no_store(JsonResponse(error.to_dict(), status=error.status))


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _first_error(form) -> str:
    for field, errors in form.errors.items():
        prefix = "" if field == "__all__" else f"{field}: "
        return prefix + str(errors[0])
    return "Invalid request"


# --- connected apps (settings UI) ---------------------------------------


@api_view(["GET"])
def list_connections(request):
    form = ListOAuthConnectionsForm({"user": request.user.id})
    if not form.is_valid():
        return Response(
            {"success": False, "errors": form.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    connections = ListOAuthConnectionsCommand(form).execute()
    return Response({"success": True, "data": {"connections": connections}})


@api_view(["POST"])
def revoke_connection(request):
    data: dict[str, Any] = request.data.copy()
    data["user"] = request.user.id
    form = RevokeOAuthConnectionForm(data)
    if not form.is_valid():
        return Response(
            {"success": False, "errors": form.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        RevokeOAuthConnectionCommand(form).execute()
    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": e.messages}},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response({"success": True, "data": {"revoked": True}})
