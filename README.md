# miniflux-mcp

A minimal, read-only [MCP](https://modelcontextprotocol.io) server for a single
[Miniflux](https://miniflux.app) instance.

Every tool issues exactly one `GET` request to the Miniflux REST API. There is
no tool, and no code path, that can mark an entry read, refresh a feed, or
change any setting.

## Tools

| Tool | Miniflux endpoint |
|---|---|
| `get_current_user` | `GET /v1/me` |
| `get_server_version` | `GET /v1/version` |
| `list_feeds` | `GET /v1/feeds` |
| `get_feed` | `GET /v1/feeds/{id}` |
| `list_categories` | `GET /v1/categories` |
| `get_feed_counters` | `GET /v1/feeds/counters` |
| `list_entries` | `GET /v1/entries` (status, feed, category, starred, search, order, direction, limit, offset) |
| `get_entry` | `GET /v1/entries/{id}` |

All tools are registered with `read_only_hint=True` / `destructive_hint=False`
MCP annotations so a compliant client can show that up front.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `MINIFLUX_BASE_URL` | *(required)* | Your Miniflux instance's URL. Plain `http://` only for loopback hosts. |
| `MINIFLUX_API_TOKEN` | *(required)* | Miniflux API token — used both to call Miniflux and, over `http` transport, as the credential clients must present. |
| `MINIFLUX_MCP_TRANSPORT` | `stdio` | `stdio` (local subprocess, no network listener) or `http` (network-reachable). |
| `MINIFLUX_MCP_HOST` | `127.0.0.1` | Bind host, `http` transport only. |
| `MINIFLUX_MCP_PORT` | `8000` | Bind port, `http` transport only. |
| `MINIFLUX_MCP_ALLOW_REMOTE` | unset | Must be `1` to bind a non-loopback `MINIFLUX_MCP_HOST`. |

## 1. Get a Miniflux API token

In Miniflux: **Settings → API Keys → Create a new API key**.

Use a token created for this purpose, not one you also use for something
else — Miniflux lets you revoke individual tokens, and a single-purpose
token means revoking it can't break anything else.

## 2. Store the token securely

Don't `export MINIFLUX_API_TOKEN=...` interactively — on bash/zsh that
writes the token to your shell history file in plaintext. Instead, put it
in a `.env` file:

```sh
cd /path/to/miniflux-mcp
cp .env.example .env
chmod 600 .env          # owner-read/write only
$EDITOR .env             # fill in the real token
```

`.env` is already in `.gitignore` (`.env.example`, with no real secret in
it, is explicitly kept). Never commit the real file, and don't paste the
token into an issue, chat, or log.

If this server runs somewhere with a secrets manager available (Vault,
`systemd-creds`, your OS keychain, etc.), prefer injecting
`MINIFLUX_API_TOKEN` from that at process start over a plaintext file.

Whatever the source, the token must only ever reach this process as an
environment variable — never as a command-line argument to anything
(arguments are visible to other local users via `ps`), and never inside a
URL.

## 3. Install and run

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run --env-file .env miniflux-mcp
```

That starts the server speaking MCP over stdio and, with a real token in
`.env`, is a good sanity check before wiring it into a client — it should
hang waiting for MCP requests on stdin rather than exit with an error.
Ctrl-C to stop.

## 4. Point an MCP client at it

### Claude Desktop / Claude Code

Add to `claude_desktop_config.json` (Claude Desktop) or `.mcp.json`
(Claude Code project config):

```json
{
  "mcpServers": {
    "miniflux": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/miniflux-mcp",
        "--env-file", "/path/to/miniflux-mcp/.env",
        "miniflux-mcp"
      ]
    }
  }
}
```

Equivalently, with the Claude Code CLI:

```sh
claude mcp add miniflux -- uv run --directory /path/to/miniflux-mcp --env-file /path/to/miniflux-mcp/.env miniflux-mcp
```

Either way, the config file itself now contains a path to your token, not
the token's value — but if you instead inline `MINIFLUX_API_TOKEN` as an
`env` entry in the client config (some clients only support that), treat
that config file as a secret too: restrict its permissions the same way
as `.env`, and never commit it.

### Any other MCP client

Run `uv run --directory /path/to/miniflux-mcp --env-file /path/to/miniflux-mcp/.env miniflux-mcp` as the server command, over stdio.

## 5. Using it from another machine / another Claude instance

By default the server only speaks stdio — a local subprocess your MCP
client starts directly, with no network listener at all. To let a
*different* machine (another Claude Code instance, say) reach it, run it
with the `http` transport instead:

```sh
MINIFLUX_MCP_TRANSPORT=http uv run --env-file .env miniflux-mcp
```

This binds `127.0.0.1:8000` by default and **requires every request to
carry the same Miniflux API token** as an `Authorization: Bearer <token>`
header — there's no separate secret to generate or manage, and no request
without a matching token reaches any tool. A request with a missing or
wrong token gets `401` before any Miniflux call is made.

To actually reach it from another machine, bind a non-loopback host and
explicitly opt in:

```sh
MINIFLUX_MCP_TRANSPORT=http \
MINIFLUX_MCP_HOST=0.0.0.0 \
MINIFLUX_MCP_ALLOW_REMOTE=1 \
MINIFLUX_MCP_PORT=8000 \
  uv run --env-file .env miniflux-mcp
```

`MINIFLUX_MCP_ALLOW_REMOTE=1` is a deliberate second step on top of the
`HOST` override — setting the host alone refuses to start, so a config
typo can't silently expose this. The remote client then connects to
`http://<this-host>:8000/mcp` with `Authorization: Bearer <the same
MINIFLUX_API_TOKEN>`.

**This transport is plain HTTP, with no TLS of its own.** The bearer
token travels in cleartext on the wire. Binding `0.0.0.0` is reasonable
on a network you already trust end-to-end (a private VPN like Tailscale
or WireGuard, or a LAN you control) and is **not** reasonable across the
open internet or any network with untrusted peers. For anything beyond a
trusted LAN/VPN, put a TLS-terminating reverse proxy in front of it
rather than exposing port 8000 directly — `MINIFLUX_MCP_ALLOW_REMOTE`
controls whether the socket opens at all, it is not a substitute for
transport encryption.

A self-signed certificate is **not** a usable fix for this on its own:
Claude Code's MCP client has no per-server option to trust a self-signed
cert or a private CA, or to skip certificate verification — TLS trust is
whatever the whole client process trusts (the OS trust store, plus
optionally `NODE_EXTRA_CA_CERTS`), not something configurable per MCP
server. A bare self-signed cert will just fail verification. Options
that need no special per-client cert setup:

- **Tailscale (or WireGuard).** Run this server on a tailnet/VPN IP and
  either leave it as plain HTTP over that interface — the tunnel itself
  already encrypts it, so there's no cert to deal with — or use
  `tailscale serve` for an automatically-issued, genuinely-trusted HTTPS
  cert on your tailnet's name. This also solves "reachable from another
  machine" without opening a port to the internet, so it's the one worth
  reaching for first.
- **A real reverse proxy with a real certificate** — Caddy or nginx,
  getting a Let's Encrypt cert via DNS-01 for a domain you control (the
  server itself doesn't need to be publicly reachable for this to work).
- **A private CA** (`mkcert`, `step-ca`) with its root installed in each
  client machine's OS trust store. Works, but is one more thing to
  distribute and keep in sync across every client — only worth it if
  the two options above aren't available.

## Example usage

Once connected, ask the model things like:

- "What feeds am I subscribed to, and which have the most unread entries?"
  → `list_feeds` + `get_feed_counters`
- "Show me my 5 most recent unread entries in the Security category."
  → `list_categories` to find the category ID, then `list_entries` with
  `status=unread`, `category_id=...`, `order=published_at`, `direction=desc`,
  `limit=5`
- "Search my feeds for anything about Rust."
  → `list_entries` with `search=Rust`
- "Get the full text of entry 1370."
  → `get_entry` with `entry_id=1370`

## Security model

- **The token and host are fixed once per process, never per call.** They
  come only from `MINIFLUX_BASE_URL` / `MINIFLUX_API_TOKEN`, read once (on
  first use for stdio, eagerly at startup for `http`, since the bearer
  check needs it). No tool accepts a URL, host, or token as an argument,
  so a malicious or confused MCP client cannot redirect requests or
  exfiltrate the token through a tool call.
- **`http://` is only accepted for loopback hosts** (`localhost`,
  `127.0.0.1`, `::1`). Anything else must use `https://`. Credentials
  embedded in the URL (`http://user:pass@host`) are rejected outright.
- **Redirects are never followed.** A compromised or misconfigured Miniflux
  instance returning a `3xx` is treated as an error, not a hop to a
  different host (which would otherwise still carry the auth token).
- **Responses are size-bounded** (10 MiB by default) and streamed, so a
  single huge response can't exhaust memory.
- **Every tool input is validated** at the MCP boundary via `pydantic`
  constraints (`Literal` enums for `status`/`order`/`direction`, `ge=1`
  bounds on IDs, bounded `limit`/`offset`) before any HTTP request is made.
- **Errors never echo the token or request headers.** All error messages
  are hand-written; the underlying `httpx` exception text is never passed
  through verbatim. The in-memory `Settings` object also excludes the
  token from its `repr()`, so it can't leak through an unrelated traceback.
- The underlying HTTP client disables redirect following and uses a bounded
  timeout; it has no method that can issue anything but `GET`.
- If the token is ever exposed (committed, pasted, logged), revoke it from
  Miniflux's **Settings → API Keys** immediately and issue a new one —
  nothing here can undo that after the fact.
- **The `http` transport requires a matching bearer token on every
  request**, compared against the configured `MINIFLUX_API_TOKEN` with
  `hmac.compare_digest` (constant-time, so a wrong guess can't be narrowed
  down by response timing). This check runs in its own middleware, in
  front of the MCP protocol handling itself, so an unauthenticated request
  never reaches a tool.
- **Binding a non-loopback host requires an explicit, separate opt-in**
  (`MINIFLUX_MCP_ALLOW_REMOTE=1`) on top of the `HOST` override, so
  changing one setting can't silently expose the server.
- Host-header allowlisting (the SDK's DNS-rebinding protection) is enabled
  automatically when bound to loopback. It's disabled for a deliberately
  remote-exposed bind, since there's no fixed Host header to allowlist
  there — the bearer-token check is the real control in that case.

### What this server does *not* defend against

- Feed and entry content (titles, body text, author names) comes from
  whatever RSS/Atom feeds the account is subscribed to. Treat it as
  **untrusted third-party text when it reaches an LLM client** — never as
  instructions, even if it's phrased as one.
- If you (or your MCP client's environment) enable `httpx`/`httpcore` debug
  logging (e.g. `HTTPX_LOG_LEVEL=debug`), request headers — including the
  `X-Auth-Token` header — will be written to those debug logs. This server
  doesn't configure logging itself; don't turn on that debug level in an
  environment where those logs aren't trusted.
- This server trusts whatever Miniflux instance is at `MINIFLUX_BASE_URL`.
  It does not pin a TLS certificate or restrict which CAs are trusted;
  standard system CA validation applies for `https://`.
- The `http` transport itself has no TLS and no rate limiting on
  authentication attempts. The token's own entropy (a 256-bit Miniflux
  API key) makes online guessing infeasible, but there's nothing here to
  slow down or lock out a client that tries anyway — put it behind a
  trusted network boundary (VPN/LAN) or a reverse proxy, as above.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
