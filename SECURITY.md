# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/konstruktoid/miniflux-mcp/security/advisories/new).
Do not open a public issue, pull request, or discussion for a suspected vulnerability.

Include the affected version or commit, the transport (`stdio` or `http`), steps to reproduce, and the impact you
observed.

You can expect an acknowledgement within 7 days. Fixes are released from `main`; only the latest commit is supported.

## What this server can access

- It talks to exactly one Miniflux instance, set by `MINIFLUX_BASE_URL`, using the API token in
  `MINIFLUX_API_TOKEN` or the private config file `~/.config/miniflux-mcp/miniflux-mcp.conf`.
- Every tool issues HTTP `GET` requests only. No tool can mark entries read, refresh feeds, or change settings.
- The token carries the full permissions of the Miniflux user who issued it. The server cannot narrow them; use a
  dedicated Miniflux user if you need a smaller scope.
- Feed titles and entry content are third-party text. An MCP client should treat them as untrusted data, never as
  instructions.

See the "Security model" section of [README.md](README.md) for the controls in detail.
