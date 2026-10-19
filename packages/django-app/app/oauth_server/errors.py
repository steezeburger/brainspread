class OAuthError(Exception):
    """An RFC 6749 error response: ``error`` is the registered code the
    client branches on, ``description`` is for humans."""

    def __init__(self, error: str, description: str = "", status: int = 400) -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status = status

    def to_dict(self) -> dict[str, str]:
        body = {"error": self.error}
        if self.description:
            body["error_description"] = self.description
        return body
