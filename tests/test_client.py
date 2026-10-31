import httpx
import pytest

from miniflux_mcp.client import MinifluxClient, MinifluxError, ResponseTooLargeError
from miniflux_mcp.config import Settings


def _client(handler, max_response_bytes=10 * 1024 * 1024):
    settings = Settings(
        base_url="http://localhost:8080",
        api_token="test-token",
        max_response_bytes=max_response_bytes,
    )
    return MinifluxClient(settings, transport=httpx.MockTransport(handler))


def test_get_json_returns_parsed_body_and_sends_token():
    def handler(request):
        assert request.headers["X-Auth-Token"] == "test-token"
        return httpx.Response(200, json={"ok": True})

    assert _client(handler).get_json("/v1/me") == {"ok": True}


@pytest.mark.parametrize(
    ("status", "match"),
    [(401, "401"), (403, "403"), (404, "404"), (500, "500")],
)
def test_get_json_error_statuses_raise(status, match):
    def handler(_request):
        return httpx.Response(status, text="error")

    with pytest.raises(MinifluxError, match=match):
        _client(handler).get_json("/v1/entries")


def test_get_json_error_message_never_contains_token():
    def handler(_request):
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(MinifluxError) as exc_info:
        _client(handler).get_json("/v1/me")
    assert "test-token" not in str(exc_info.value)


def test_get_json_refuses_redirect_instead_of_following():
    def handler(_request):
        return httpx.Response(302, headers={"Location": "http://internal.example/"})

    with pytest.raises(MinifluxError, match="redirect"):
        _client(handler).get_json("/v1/feeds")


def test_get_json_enforces_response_size_cap():
    big_body = b"[" + b"1," * 1000 + b"1]"

    def handler(_request):
        return httpx.Response(200, content=big_body)

    with pytest.raises(ResponseTooLargeError):
        _client(handler, max_response_bytes=10).get_json("/v1/entries")


def test_get_json_only_ever_issues_get():
    seen_methods = []

    def handler(request):
        seen_methods.append(request.method)
        return httpx.Response(200, json=[])

    client = _client(handler)
    client.get_json("/v1/feeds")
    client.get_json("/v1/categories", params={"x": 1, "y": None})
    assert seen_methods == ["GET", "GET"]


def test_get_json_drops_none_params():
    def handler(request):
        assert dict(request.url.params) == {"x": "1"}
        return httpx.Response(200, json=[])

    _client(handler).get_json("/v1/categories", params={"x": 1, "y": None})


def test_get_json_sends_list_params_as_repeated_query_keys():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["tags"] = request.url.params.get_list("tags")
        return httpx.Response(200, json={"total": 0, "entries": []})

    client = MinifluxClient(
        Settings(base_url="https://reader.example.com", api_token="t"),
        transport=httpx.MockTransport(handler),
    )
    client.get_json("/v1/entries", params={"tags": ["a", "b"]})
    assert seen["tags"] == ["a", "b"]


@pytest.mark.parametrize(
    ("exc_type", "match"),
    [(httpx.ReadTimeout, "timed out"), (httpx.ConnectError, "Could not reach")],
)
def test_get_json_wraps_transport_failures(exc_type, match):
    def handler(request):
        raise exc_type("boom", request=request)

    with pytest.raises(MinifluxError, match=match) as excinfo:
        _client(handler).get_json("/v1/me")
    assert "test-token" not in str(excinfo.value)


def test_get_json_rejects_non_json_body():
    def handler(_request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(MinifluxError, match="non-JSON"):
        _client(handler).get_json("/v1/me")
