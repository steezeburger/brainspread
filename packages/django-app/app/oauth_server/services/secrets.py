import base64
import hashlib
import secrets


def generate_secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 S256: BASE64URL(SHA256(verifier)) without padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)
