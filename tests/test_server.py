import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import miniflux_mcp.server as server_module
from miniflux_mcp.config import Settings
from miniflux_mcp.server import mcp


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        return {"path": path, "params": params}


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(server_module, "_client", fake)
    return fake


def _call(name, args):
    return asyncio.run(mcp.call_tool(name, args))


def test_list_entries_passes_validated_args_through(fake_client):
    _call("list_entries", {"status": "unread", "limit": 5})
    assert fake_client.calls == [
        (
            "/v1/entries",
            {
                "status": "unread",
                "feed_id": None,
                "category_id": None,
                "starred": None,
                "search": None,
                "tags": None,
                "order": "published_at",
                "direction": "desc",
                "limit": 5,
                "offset": 0,
            },
        )
    ]


def test_list_entries_passes_tags_and_new_orders_through(fake_client):
    _call("list_entries", {"tags": ["security", "rust"], "order": "created_at"})
    path, params = fake_client.calls[0]
    assert path == "/v1/entries"
    assert params["tags"] == ["security", "rust"]
    assert params["order"] == "created_at"


@pytest.mark.parametrize(
    "args",
    [
        {"status": "bogus"},
        {"status": "removed"},
        {"tags": []},
        {"tags": [""]},
        {"tags": ["x"] * 21},
        {"order": "bogus"},
        {"direction": "bogus"},
        {"limit": 0},
        {"limit": 251},
        {"offset": -1},
    ],
)
def test_list_entries_rejects_invalid_args_before_any_call(args, fake_client):
    with pytest.raises(ToolError):
        _call("list_entries", args)
    assert fake_client.calls == []


@pytest.mark.parametrize("feed_id", [0, -1])
def test_get_feed_rejects_non_positive_id(feed_id, fake_client):
    with pytest.raises(ToolError):
        _call("get_feed", {"feed_id": feed_id})
    assert fake_client.calls == []


def test_get_entry_rejects_non_positive_id(fake_client):
    with pytest.raises(ToolError):
        _call("get_entry", {"entry_id": 0})
    assert fake_client.calls == []


def test_get_feed_passes_valid_id_through(fake_client):
    _call("get_feed", {"feed_id": 42})
    assert fake_client.calls == [("/v1/feeds/42", None)]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_current_user", {}),
        ("get_server_version", {}),
        ("list_feeds", {}),
        ("list_categories", {}),
        ("get_feed_counters", {}),
    ],
)
def test_no_argument_tools_reach_the_client(name, args, fake_client):
    _call(name, args)
    assert len(fake_client.calls) == 1


def test_all_registered_tools_are_marked_read_only():
    tools = asyncio.run(mcp.list_tools())
    assert tools
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


def test_get_client_is_created_once_and_reused(monkeypatch):
    monkeypatch.setattr(server_module, "_client", None)
    monkeypatch.setattr(
        server_module,
        "load_settings",
        lambda: Settings(base_url="http://localhost:8080", api_token="t"),
    )

    first = server_module._get_client()
    try:
        assert server_module._get_client() is first
    finally:
        first.close()


def test_main_runs_stdio_without_loading_the_token(monkeypatch):
    calls = []
    monkeypatch.delenv("MINIFLUX_MCP_TRANSPORT", raising=False)
    monkeypatch.setattr(server_module.mcp, "run", lambda **kw: calls.append(kw))
    monkeypatch.setattr(
        server_module, "load_settings", lambda: pytest.fail("token loaded eagerly")
    )
    monkeypatch.setattr(
        server_module, "run_http", lambda *a: pytest.fail("http started")
    )

    server_module.main()
    assert calls == [{"transport": "stdio"}]


def test_main_runs_http_with_the_miniflux_token(monkeypatch):
    calls = []
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setattr(
        server_module,
        "load_settings",
        lambda: Settings(base_url="http://localhost:8080", api_token="tok"),
    )
    monkeypatch.setattr(
        server_module,
        "run_http",
        lambda mcp_, transport, token: calls.append((transport, token)),
    )

    server_module.main()
    ((transport, token),) = calls
    assert transport.transport == "http"
    assert transport.host == "127.0.0.1"
    assert token == "tok"
