import base64
import hashlib
import secrets
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpRequest

from .constants import MCP_RESOURCE_PATHS


def generate_secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 S256: BASE64URL(SHA256(verifier)) without padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def issuer_url(request: HttpRequest) -> str:
    """Public origin of this server, no trailing slash.

    SITE_URL wins when it's a real URL: behind the prod proxy Django
    sees plain http, but the issuer and resource URLs Claude compares
    against have to be the https ones the user typed.
    """
    site_url = getattr(settings, "SITE_URL", "") or ""
    if site_url.startswith(("http://", "https://")):
        return site_url.rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


def resource_metadata_url(request: HttpRequest, resource_path: str) -> str:
    return f"{issuer_url(request)}/.well-known/oauth-protected-resource{resource_path}"


def is_mcp_resource(resource: str) -> bool:
    """RFC 8707 ``resource`` check. Only the path is compared: tokens are
    only ever accepted by this server, and a strict host comparison
    would break whenever SITE_URL and the typed host differ in
    spelling."""
    return urlsplit(resource).path in MCP_RESOURCE_PATHS


def is_loopback_redirect(uri: str) -> bool:
    parts = urlsplit(uri)
    return parts.scheme == "http" and (parts.hostname or "") in {
        h.strip("[]") for h in LOOPBACK_HOSTS
    }


def is_valid_redirect_uri(uri: str) -> bool:
    """https anywhere, or http on a loopback host (native clients like
    Claude Code). No fragments, per RFC 6749 3.1.2."""
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    return parts.scheme == "https" or is_loopback_redirect(uri)


def redirect_uri_matches(requested: str, registered: list[str]) -> bool:
    """Exact match, except loopback URIs match on any port (RFC 8252
    7.3): Claude Code registers ``http://localhost/callback`` and then
    redirects to whatever ephemeral port it bound."""
    if requested in registered:
        return True
    if not is_loopback_redirect(requested):
        return False
    req = urlsplit(requested)
    for uri in registered:
        reg = urlsplit(uri)
        if (
            is_loopback_redirect(uri)
            and reg.hostname == req.hostname
            and reg.path == req.path
            and reg.query == req.query
        ):
            return True
    return False


def add_query_params(uri: str, params: dict[str, Optional[str]]) -> str:
    parts = urlsplit(uri)
    extra = urlencode({k: v for k, v in params.items() if v is not None})
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit(parts._replace(query=query))
