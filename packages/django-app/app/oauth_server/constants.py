from datetime import timedelta

# The one scope MCP tokens carry. offline_access is advertised too so
# Claude asks for (and expects) a refresh token.
MCP_SCOPE = "mcp"
SCOPES_SUPPORTED = [MCP_SCOPE, "offline_access"]

ACCESS_TOKEN_PREFIX = "bsat_"
REFRESH_TOKEN_PREFIX = "bsrt_"
CLIENT_ID_PREFIX = "bsc_"

AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=10)
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
# Sliding: every refresh issues a new refresh token with a fresh window,
# so a client that's used at least this often never has to re-consent.
REFRESH_TOKEN_LIFETIME = timedelta(days=90)
# A rotated refresh token presented again within this window is treated
# as a client racing itself (two refreshes in flight), not as theft.
REFRESH_REUSE_GRACE = timedelta(seconds=30)

# Paths the MCP endpoint answers on; both spellings are valid resources.
MCP_RESOURCE_PATHS = ("/api/mcp/", "/api/mcp")
