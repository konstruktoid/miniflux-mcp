import pytest

from miniflux_mcp.config import (
    ConfigError,
    Settings,
    TransportSettings,
    is_loopback_host,
    load_settings,
    load_transport_settings,
)


def test_load_settings_requires_base_url(monkeypatch):
    monkeypatch.delenv("MINIFLUX_BASE_URL", raising=False)
    monkeypatch.setenv("MINIFLUX_API_TOKEN", "token")
    with pytest.raises(ConfigError, match="MINIFLUX_BASE_URL"):
        load_settings()


def test_load_settings_requires_api_token(monkeypatch):
    monkeypatch.setenv("MINIFLUX_BASE_URL", "http://localhost:8080")
    monkeypatch.delenv("MINIFLUX_API_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="MINIFLUX_API_TOKEN"):
        load_settings()


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8080", "http://127.0.0.1:8080", "https://reader.example.com"],
)
def test_load_settings_accepts_safe_base_urls(monkeypatch, base_url):
    monkeypatch.setenv("MINIFLUX_BASE_URL", base_url)
    monkeypatch.setenv("MINIFLUX_API_TOKEN", "token")
    settings = load_settings()
    assert settings.base_url == base_url.rstrip("/")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com",
        "http://reader.internal",
        "ftp://localhost:8080",
        "http://user:pass@localhost:8080",
        "http://",
        "not-a-url",
    ],
)
def test_load_settings_rejects_unsafe_base_urls(monkeypatch, base_url):
    monkeypatch.setenv("MINIFLUX_BASE_URL", base_url)
    monkeypatch.setenv("MINIFLUX_API_TOKEN", "token")
    with pytest.raises(ConfigError):
        load_settings()


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.2",  # anything in 127.0.0.0/8 is loopback, not just .1
        "localhost",
        "::1",
        "0:0:0:0:0:0:0:1",  # expanded form of the same IPv6 loopback address
    ],
)
def test_is_loopback_host_accepts_loopback_forms(host):
    assert is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["example.com", "10.0.0.1", "0.0.0.0", "192.168.1.1"])
def test_is_loopback_host_rejects_non_loopback(host):
    assert is_loopback_host(host) is False


def test_settings_repr_excludes_token():
    settings = Settings(
        base_url="http://localhost:8080", api_token="super-secret-token"
    )
    assert "super-secret-token" not in repr(settings)


@pytest.fixture(autouse=True)
def _clean_transport_env(monkeypatch):
    for name in (
        "MINIFLUX_MCP_TRANSPORT",
        "MINIFLUX_MCP_HOST",
        "MINIFLUX_MCP_PORT",
        "MINIFLUX_MCP_ALLOW_REMOTE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_transport_settings_defaults_to_stdio():
    assert load_transport_settings() == TransportSettings(transport="stdio")


def test_load_transport_settings_rejects_unknown_transport(monkeypatch):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "bogus")
    with pytest.raises(ConfigError, match="MINIFLUX_MCP_TRANSPORT"):
        load_transport_settings()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_load_transport_settings_accepts_loopback_http_without_opt_in(
    monkeypatch, host
):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setenv("MINIFLUX_MCP_HOST", host)
    settings = load_transport_settings()
    assert settings == TransportSettings(transport="http", host=host, port=8000)


def test_load_transport_settings_rejects_non_loopback_http_without_opt_in(monkeypatch):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setenv("MINIFLUX_MCP_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="MINIFLUX_MCP_ALLOW_REMOTE"):
        load_transport_settings()


def test_load_transport_settings_accepts_non_loopback_http_with_opt_in(monkeypatch):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setenv("MINIFLUX_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MINIFLUX_MCP_ALLOW_REMOTE", "1")
    settings = load_transport_settings()
    assert settings == TransportSettings(transport="http", host="0.0.0.0", port=8000)


def test_load_transport_settings_rejects_non_integer_port(monkeypatch):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setenv("MINIFLUX_MCP_PORT", "not-a-port")
    with pytest.raises(ConfigError, match="MINIFLUX_MCP_PORT"):
        load_transport_settings()


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_load_transport_settings_rejects_out_of_range_port(monkeypatch, port):
    monkeypatch.setenv("MINIFLUX_MCP_TRANSPORT", "http")
    monkeypatch.setenv("MINIFLUX_MCP_PORT", str(port))
    with pytest.raises(ConfigError, match="MINIFLUX_MCP_PORT"):
        load_transport_settings()
