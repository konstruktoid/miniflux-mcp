# miniflux-mcp

A minimal, read-only [MCP](https://modelcontextprotocol.io) server for a single
[Miniflux](https://miniflux.app) instance, targeting Miniflux **2.3.4**
(the latest release). Older servers are not supported.

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
| `list_entries` | `GET /v1/entries` (status, feed_id, category_id, starred, search, tags, order, direction, limit, offset) |
| `get_entry` | `GET /v1/entries/{id}` |

All tools are registered with `read_only_hint=True`, `destructive_hint=False`,
`idempotent_hint=True`, and `open_world_hint=False` MCP annotations so a
compliant client can show that up front.

`list_entries` follows the Miniflux 2.3 API: `status` is `unread` or `read`
(the old `removed` status no longer exists); `tags` takes 1–20 tags and
matches only entries carrying *all* of them, case-insensitively; `order`
also accepts `changed_at` and `created_at`; `limit` is 1–250 (default 20).
Feeds and entries include the `language` field added in 2.3.3.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `MINIFLUX_BASE_URL` | *(required)* | Your Miniflux instance's URL. Plain `http://` only for loopback hosts. Falls back to `~/.config/miniflux-mcp/miniflux-mcp.conf` if unset. |
| `MINIFLUX_API_TOKEN` | *(required)* | Miniflux API token — used both to call Miniflux and, over `http` transport, as the credential clients must present. Falls back to `~/.config/miniflux-mcp/miniflux-mcp.conf` if unset. |
| `MINIFLUX_MCP_TRANSPORT` | `stdio` | `stdio` (local subprocess, no network listener) or `http` (network-reachable). |
| `MINIFLUX_MCP_HOST` | `127.0.0.1` | Bind host, `http` transport only. |
| `MINIFLUX_MCP_PORT` | `8000` | Bind port, `http` transport only. |
| `MINIFLUX_MCP_ALLOW_REMOTE` | unset | Must be `1` to bind a non-loopback `MINIFLUX_MCP_HOST`. |
| `XDG_CONFIG_HOME` | `~/.config` | Base directory for the config file, read as `$XDG_CONFIG_HOME/miniflux-mcp/miniflux-mcp.conf`. |

The Miniflux request timeout (10 s) and response size cap (10 MiB) are fixed
in code, not configurable.

## 1. Get a Miniflux API token

In Miniflux: **Settings → API Keys → Create a new API key**.

Use a token created for this purpose, not one you also use for something
else — Miniflux lets you revoke individual tokens, and a single-purpose
token means revoking it can't break anything else.

## 2. Store the token securely

Don't `export MINIFLUX_API_TOKEN=...` interactively — on bash/zsh that
writes the token to your shell history file in plaintext. Instead, put it
in `~/.config/miniflux-mcp/miniflux-mcp.conf`:

```sh
mkdir -p ~/.config/miniflux-mcp
$EDITOR ~/.config/miniflux-mcp/miniflux-mcp.conf
chmod 600 ~/.config/miniflux-mcp/miniflux-mcp.conf   # owner-read/write only
```

with contents:

```sh
MINIFLUX_BASE_URL=http://localhost:8080
MINIFLUX_API_TOKEN=replace-with-a-real-miniflux-api-token
```

One `KEY=VALUE` per line. `# comments`, blank lines, and spaces around `=`
are allowed; a value wrapped in matching single or double quotes has them
stripped; lines without `=` and unknown keys are ignored. This file lives
outside the repo, so there's nothing to `.gitignore` here — never copy it
into the project directory, and don't paste the token into an issue, chat,
or log. The server refuses to read this file unless it is a regular file
and, on Linux/macOS, owned by the user running the server with no group
or other permission bits (`ConfigError` naming the exact `chmod` to run),
so a permissions mistake fails loudly instead of silently leaking the
token to other local users. On Windows only the regular-file check
applies.

Either `MINIFLUX_BASE_URL` or `MINIFLUX_API_TOKEN` can instead be set as
an environment variable, which always takes precedence over the config
file when both are present. A variable that is set but empty (or only
whitespace) counts as unset, so the config file value is used. If this
server runs somewhere with a secrets manager available (Vault,
`systemd-creds`, your OS keychain, etc.),
prefer injecting `MINIFLUX_API_TOKEN` as an environment variable from
that at process start over the config file.

Whatever the source, the token must only ever reach this process as an
environment variable or via the config file above — never as a
command-line argument to anything (arguments are visible to other local
users via `ps`), and never inside a URL.

## 3. Install and run

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer, and a
Miniflux 2.3.4 server.

```sh
uv sync
uv run miniflux-mcp
```

That starts the server speaking MCP over stdio; it waits for MCP requests
on stdin. Ctrl-C to stop. Over stdio the configuration is only read on the
first tool call, so a missing or unsafe config file does not stop it from
starting. To check the configuration up front, without printing the token:

```sh
uv run python -c 'from miniflux_mcp.config import load_settings; print(load_settings().base_url)'
```

This prints your Miniflux URL, or the `ConfigError` explaining what is
wrong. Once a client is connected, the `get_server_version` tool confirms
the token works end to end.

## 4. Point an MCP client at it

### Claude Desktop / Claude Code

Add to `claude_desktop_config.json` (Claude Desktop) or a project's
`.mcp.json` (Claude Code, shared with everyone who uses the project):

```json
{
  "mcpServers": {
    "miniflux": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/miniflux-mcp", "miniflux-mcp"]
    }
  }
}
```

Or with the Claude Code CLI, which by default registers it for you only,
in the current project (`--scope user` for all your projects, `--scope
project` to write `.mcp.json` instead):

```sh
claude mcp add miniflux -- uv run --directory /path/to/miniflux-mcp miniflux-mcp
```

After pulling a new version of this repository, reconnect the server
(`/mcp` in Claude Code) so the client starts the updated code.

Either way, the client config contains no secret at all — the token
comes from `~/.config/miniflux-mcp/miniflux-mcp.conf` on whatever machine
runs the server. If you instead inline `MINIFLUX_API_TOKEN` as an `env`
entry in the client config (some clients only support that), treat that
config file as a secret too: restrict its permissions the same way as
`miniflux-mcp.conf`, and never commit it.

### Any other MCP client

Run `uv run --directory /path/to/miniflux-mcp miniflux-mcp` as the server
command, over stdio.

## 5. Using it from another machine / another Claude instance

By default the server only speaks stdio — a local subprocess your MCP
client starts directly, with no network listener at all. To let a
*different* machine (another Claude Code instance, say) reach it, run it
with the `http` transport instead:

```sh
MINIFLUX_MCP_TRANSPORT=http uv run miniflux-mcp
```

This binds `127.0.0.1:8000` by default and **requires every request to
carry the same Miniflux API token** as an `Authorization: Bearer <token>`
header — there's no separate secret to generate or manage, and no request
without a matching token reaches any tool. A request with a missing or
wrong token gets `401` (a WebSocket is closed with code `1008`) before any
Miniflux call is made. In this mode the configuration is read at startup,
so a missing or unsafe config file stops the server immediately.

To actually reach it from another machine, bind a non-loopback host and
explicitly opt in:

```sh
MINIFLUX_MCP_TRANSPORT=http \
MINIFLUX_MCP_HOST=0.0.0.0 \
MINIFLUX_MCP_ALLOW_REMOTE=1 \
MINIFLUX_MCP_PORT=8000 \
  uv run miniflux-mcp
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
- "Show entries tagged security, newest first by when Miniflux fetched them."
  → `list_entries` with `tags=["security"]`, `order=created_at` (tag
  matching ignores case, so this also finds entries tagged `Security`)
- "Get the full text of entry 1370."
  → `get_entry` with `entry_id=1370`

## Security model

- **The token and host are fixed once per process, never per call.** They
  come only from `MINIFLUX_BASE_URL` / `MINIFLUX_API_TOKEN` (an env var,
  or the `~/.config/miniflux-mcp/miniflux-mcp.conf` fallback — an env var
  always wins if both are set), read once (on first use for stdio,
  eagerly at startup for `http`, since the bearer check needs it). No tool
  accepts a URL, host, or token as an argument, so a malicious or confused
  MCP client cannot redirect requests or exfiltrate the token through a
  tool call.
- **On POSIX systems the config file is refused unless it is a private
  regular file.** It must be owned by the user running the server and
  have no group or other permission bits (for example `600` or `400`);
  anything else raises a `ConfigError` naming the exact command to fix it.
  On every platform, a directory, FIFO, or other special file at that path
  is rejected without blocking, rather than silently loading a token
  other local users could read or plant. **On Windows the file's ACL is
  not checked**: restrict access to your own account yourself (for
  example with `icacls`) before storing a token in it.
- **`http://` is only accepted for loopback hosts** (`localhost`,
  `127.0.0.1`, `::1`). Anything else must use `https://`. Credentials
  embedded in the URL (`http://user:pass@host`) are rejected outright.
- **Redirects are never followed.** A compromised or misconfigured Miniflux
  instance returning a `3xx` is treated as an error, not a hop to a
  different host (which would otherwise still carry the auth token).
- **Responses are size-bounded** (10 MiB) and streamed, so a single huge
  response can't exhaust memory.
- **Every tool input is validated** at the MCP boundary via `pydantic`
  constraints (`Literal` enums for `status`/`order`/`direction`, `ge=1`
  bounds on IDs, bounded `limit`/`offset`, length limits on `search` and on
  each of at most 20 `tags`) before any HTTP request is made.
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
  never reaches a tool. It fails closed: HTTP, WebSocket, and any other
  connection type all need the token, and only the server's own
  startup/shutdown (ASGI lifespan) events bypass it. Rejected requests are
  logged with the path escaped, so a crafted path can't forge log lines.
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
- This server doesn't configure logging for its Miniflux HTTP client. If
  something in the same process turns on `DEBUG` logging for the `httpx` or
  `httpcore` loggers, those logs describe every request sent with the
  `X-Auth-Token` header; treat such logs as sensitive, and don't enable
  that level where the logs aren't trusted.
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
uv run ty check   # type check
uv audit          # dependency vulnerability scan (preview feature in uv)
```

CI (`.github/workflows/ci.yml`) runs the tests, ruff, and ty on every pull
request and on pushes to `main`; CodeQL code scanning runs alongside it.
`main` only accepts signed commits through a pull request, and Dependabot
proposes weekly grouped updates for uv and GitHub Actions dependencies.

## Reporting a vulnerability

See [SECURITY.md](SECURITY.md). Use GitHub private vulnerability
reporting, not a public issue.
