"""Lifetimes and shared constants for the MCP OAuth flow."""

from datetime import timedelta

AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=10)
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)

# The only PKCE method OAuth 2.1 allows for public clients.
CODE_CHALLENGE_METHOD = "S256"
