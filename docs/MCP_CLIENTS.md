# Connecting MCP clients to brainspread

Brainspread ships an MCP (Model Context Protocol) server at
`POST /api/mcp/` exposing tools for pages, blocks, TODOs, scheduling,
and tags. Two auth schemes are supported, and every tool operates as
the authenticated user:

| Scheme                        | Header                     | Best for                                  |
| ----------------------------- | -------------------------- | ----------------------------------------- |
| OAuth 2.1 (PKCE)              | `Authorization: Bearer …`  | Claude Desktop / claude.ai custom connectors |
| DRF token                     | `Authorization: Token …`   | Scripts, stdio bridges like `mcp-remote`  |

## Option 1 — Claude custom connector (OAuth, recommended)

Requires brainspread to be reachable by the Claude app at an HTTPS URL
(a deployed instance, or a tunnel like `ngrok`/`cloudflared` in front
of your local server).

1. In Claude (Desktop or claude.ai): **Settings → Connectors → Add
   custom connector**.
2. Enter your MCP endpoint URL, including the trailing slash:
   `https://<your-brainspread-host>/api/mcp/`
3. Claude discovers the OAuth server via
   `/.well-known/oauth-protected-resource`, registers itself as a
   client, and opens brainspread's authorization page in the browser.
4. Log in (if you don't have a live session) and click **approve**.

That's it — Claude stores the tokens and refreshes them automatically.
Access tokens last 1 hour; refresh tokens rotate on every refresh and
die if revoked.

Under the hood the flow is standard OAuth 2.1:

- `GET /.well-known/oauth-authorization-server` — RFC 8414 metadata
- `GET /.well-known/oauth-protected-resource` — RFC 9728 metadata
- `POST /oauth/register` — RFC 7591 dynamic client registration
  (public clients, no secret; PKCE S256 is mandatory)
- `GET|POST /oauth/authorize` — consent page + code issuance
- `POST /oauth/token` — code exchange and refresh-token rotation

## Option 2 — mcp-remote bridge (DRF token, no HTTPS needed)

Works against plain `http://localhost:8001` with your existing account
token. Useful when you don't want to expose the server publicly.

1. Get your API token — it's returned by the login endpoint:

   ```bash
   curl -s http://localhost:8001/api/auth/login/ \
     -H 'Content-Type: application/json' \
     -d '{"email": "you@example.com", "password": "..."}' | jq -r .data.token
   ```

2. Add to `claude_desktop_config.json` (Claude Desktop → Settings →
   Developer → Edit Config):

   ```json
   {
     "mcpServers": {
       "brainspread": {
         "command": "npx",
         "args": [
           "mcp-remote",
           "http://localhost:8001/api/mcp/",
           "--header",
           "Authorization:${AUTH_HEADER}",
           "--allow-http",
           "--transport", "http-only"
         ],
         "env": { "AUTH_HEADER": "Token <your-token>" }
       }
     }
   }
   ```

3. Restart Claude Desktop.

Gotchas:

- Keep the trailing slash on `/api/mcp/` — without it Django's
  APPEND_SLASH redirect drops the POST body.
- The header value goes through `env` because `mcp-remote` splits a
  space inside a `--header` argument.
- Requires Node.js (`npx`) on your PATH.

## Transport notes

The server speaks Streamable HTTP: a single stateless
`POST /api/mcp/` JSON-RPC endpoint that always answers
`application/json`. There is no SSE stream, no session header, and no
stdio transport — all tools complete synchronously, and both Claude
connectors and `mcp-remote` work with plain POST round-trips.
