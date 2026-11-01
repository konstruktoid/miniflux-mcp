import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from miniflux_mcp import http_transport
from miniflux_mcp.config import TransportSettings
from miniflux_mcp.http_transport import (
    BearerTokenMiddleware,
    build_app,
    transport_security_for,
)
from miniflux_mcp.server import mcp


def _protected_app(expected_token: str) -> Starlette:
    async def ok(_request):
        return PlainTextResponse("ok")

    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    app = Starlette(
        routes=[Route("/mcp", ok, methods=["POST"]), WebSocketRoute("/ws", ws)]
    )
    app.add_middleware(BearerTokenMiddleware, expected_token=expected_token)
    return app


def test_missing_authorization_header_is_rejected():
    client = TestClient(_protected_app("secret-token"))
    response = client.post("/mcp")
    assert response.status_code == 401
    assert "secret-token" not in response.text


def test_wrong_token_is_rejected():
    client = TestClient(_protected_app("secret-token"))
    response = client.post("/mcp", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_malformed_authorization_header_is_rejected():
    client = TestClient(_protected_app("secret-token"))
    response = client.post("/mcp", headers={"Authorization": "secret-token"})
    assert response.status_code == 401


def test_websocket_without_token_is_rejected():
    client = TestClient(_protected_app("secret-token"))
    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect("/ws"):
        pass
    assert excinfo.value.code == 1008


def test_websocket_with_token_reaches_the_app():
    client = TestClient(_protected_app("secret-token"))
    with client.websocket_connect(
        "/ws", headers={"Authorization": "Bearer secret-token"}
    ) as ws:
        assert ws.receive_text() == "ok"


def test_correct_token_reaches_the_app():
    client = TestClient(_protected_app("secret-token"))
    response = client.post("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.parametrize(
    ("host", "header"),
    [
        ("127.0.0.1", "127.0.0.1:8000"),
        ("127.0.0.2", "127.0.0.2:8000"),
        ("localhost", "localhost:8000"),
        ("::1", "[::1]:8000"),
    ],
)
def test_transport_security_enables_dns_rebinding_protection_on_loopback(host, header):
    security = transport_security_for(host, 8000)
    assert security.enable_dns_rebinding_protection is True
    assert header in security.allowed_hosts


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "203.0.113.1"])
def test_transport_security_disables_dns_rebinding_protection_off_loopback(host):
    security = transport_security_for(host, 8000)
    assert security.enable_dns_rebinding_protection is False
    assert security.allowed_hosts == []


def test_non_http_scope_passes_through_untouched():
    events: list[str] = []

    class _InnerApp:
        async def __call__(self, scope, receive, send):
            events.append(scope["type"])

    middleware = BearerTokenMiddleware(_InnerApp(), expected_token="secret-token")

    import asyncio

    async def _receive():
        return {"type": "lifespan.startup"}

    async def _send(_message):
        pass

    asyncio.run(middleware({"type": "lifespan"}, _receive, _send))
    assert events == ["lifespan"]


def test_unknown_scope_type_fails_closed():
    reached = []
    sent = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    async def receive():
        return {}

    async def send(message):
        sent.append(message)

    middleware = BearerTokenMiddleware(inner, expected_token="secret-token")
    asyncio.run(
        middleware({"type": "custom", "headers": [], "path": "/"}, receive, send)
    )
    assert reached == []
    assert sent[0]["status"] == 401


_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def test_build_app_puts_the_real_mcp_endpoint_behind_the_token():
    app = build_app(mcp, TransportSettings(transport="http"), "secret-token")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        denied = client.post("/mcp", json=_INITIALIZE, headers=_MCP_HEADERS)
        allowed = client.post(
            "/mcp",
            json=_INITIALIZE,
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret-token"},
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_run_http_serves_the_built_app_on_the_configured_address(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))

    http_transport.run_http(
        mcp, TransportSettings(transport="http", port=8123), "secret-token"
    )
    ((app, kwargs),) = calls
    assert isinstance(app, Starlette)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8123
