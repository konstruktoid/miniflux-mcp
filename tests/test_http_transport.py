import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from miniflux_mcp.http_transport import BearerTokenMiddleware, transport_security_for


def _protected_app(expected_token: str) -> Starlette:
    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", ok, methods=["POST"])])
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


def test_correct_token_reaches_the_app():
    client = TestClient(_protected_app("secret-token"))
    response = client.post("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
def test_transport_security_enables_dns_rebinding_protection_on_loopback(host):
    security = transport_security_for(host, 8000)
    assert security.enable_dns_rebinding_protection is True
    assert f"{host}:8000" in security.allowed_hosts


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
