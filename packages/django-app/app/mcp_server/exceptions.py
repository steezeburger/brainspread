"""Domain errors for the MCP OAuth flow."""


class OAuthError(Exception):
    """An RFC 6749 protocol error.

    ``error`` is the machine-readable code the spec defines
    (``invalid_grant``, ``invalid_client``, ...); ``description`` is
    the human-readable detail returned as ``error_description``.
    """

    def __init__(self, error: str, description: str) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
