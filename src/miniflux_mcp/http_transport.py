"""Network (streamable-http) transport, gated behind a bearer-token check.

stdio has no equivalent of this module: a local subprocess is already
scoped to whoever can run it. Exposing this server over HTTP instead means
anyone who can reach the port can read the Miniflux account's feeds and
entries, so every request here must present the same Miniflux API token
this server uses, as an `Authorization: Bearer <token>` header, checked in
constant time. There is no separate app-level secret to manage.
"""

from __future__ import annotations

import hmac
import logging

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette import status
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from .config import TransportSettings, is_loopback_host

logger = logging.getLogger(__name__)


class BearerTokenMiddleware:
    """Reject any HTTP or WebSocket connection that doesn't carry the configured Miniflux token.

    Only the lifespan scope bypasses the check; any other scope type fails closed, so a
    route added later cannot become reachable without the token.
    """

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self._app = app
        self._expected_token = expected_token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return

        if not self._is_authorized(Headers(scope=scope).get("authorization")):
            # %r escapes control characters so a crafted path cannot forge extra log lines.
            logger.warning("Rejected unauthenticated request to %r", scope.get("path"))
            if scope["type"] == "websocket":
                await WebSocketClose(code=status.WS_1008_POLICY_VIOLATION)(
                    scope, receive, send
                )
            else:
                await PlainTextResponse("Unauthorized", status_code=401)(
                    scope, receive, send
                )
            return

        await self._app(scope, receive, send)

    def _is_authorized(self, header_value: str | None) -> bool:
        if not header_value or not header_value.startswith("Bearer "):
            return False
        presented = header_value.removeprefix("Bearer ").strip().encode("utf-8")
        return hmac.compare_digest(presented, self._expected_token)


def _host_header(host: str, port: int) -> str:
    """Format host and port as a client sends them in the Host header, bracketing IPv6 literals."""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def transport_security_for(host: str, port: int) -> TransportSecuritySettings:
    """Decide Host-header allowlisting for a given bind address.

    Host-header allowlisting only works for a fixed, known bind address; a
    deliberately remote-exposed server can be reached by any address that
    routes to it, so the bearer token is the real control in that case.
    """
    if not is_loopback_host(host):
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=False, allowed_hosts=[], allowed_origins=[]
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_host_header(host, port), f"localhost:{port}"],
        allowed_origins=[],
    )


def build_app(
    mcp: MCPServer, transport: TransportSettings, api_token: str
) -> Starlette:
    """Build the Starlette app for the http transport, auth middleware included."""
    security = transport_security_for(transport.host, transport.port)
    app = mcp.streamable_http_app(host=transport.host, transport_security=security)
    app.add_middleware(BearerTokenMiddleware, expected_token=api_token)
    return app


def run_http(mcp: MCPServer, transport: TransportSettings, api_token: str) -> None:
    import uvicorn

    app = build_app(mcp, transport, api_token)
    uvicorn.run(app, host=transport.host, port=transport.port, log_level="info")
