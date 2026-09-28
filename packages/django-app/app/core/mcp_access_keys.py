import hashlib
import secrets

# Every MCP access key starts with this, so the authentication class
# can tell one apart from a legacy DRF token without a DB lookup.
MCP_ACCESS_KEY_PREFIX = "bsmcp_"
# How much of the key the settings UI shows to tell tokens apart.
MCP_ACCESS_KEY_DISPLAY_LENGTH = 12


def generate_mcp_access_key() -> str:
    return MCP_ACCESS_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_mcp_access_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def is_mcp_access_key(key: str) -> bool:
    return key.startswith(MCP_ACCESS_KEY_PREFIX)
