import os

import pytest

from miniflux_mcp.config import (
    ConfigError,
    Settings,
    TransportSettings,
    config_file_path,
    is_loopback_host,
    load_settings,
    load_transport_settings,
)


@pytest.fixture(autouse=True)
def _isolated_config_dir(monkeypatch, tmp_path):
    """Point the fallback config file at an empty tmp dir, never the real one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


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


def test_load_settings_reads_config_file_fallback(monkeypatch):
    monkeypatch.delenv("MINIFLUX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIFLUX_API_TOKEN", raising=False)
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# comment\nMINIFLUX_BASE_URL=http://localhost:8080\n"
        "MINIFLUX_API_TOKEN=from-file\n"
    )
    path.chmod(0o600)

    settings = load_settings()
    assert settings.base_url == "http://localhost:8080"
    assert settings.api_token == "from-file"


def test_load_settings_env_var_overrides_config_file(monkeypatch):
    monkeypatch.setenv("MINIFLUX_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("MINIFLUX_API_TOKEN", "from-env")
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("MINIFLUX_API_TOKEN=from-file\n")
    path.chmod(0o600)

    settings = load_settings()
    assert settings.api_token == "from-env"


def test_load_settings_rejects_group_readable_config_file(monkeypatch):
    monkeypatch.delenv("MINIFLUX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIFLUX_API_TOKEN", raising=False)
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("MINIFLUX_API_TOKEN=from-file\n")
    path.chmod(0o640)

    with pytest.raises(ConfigError, match="readable by users other than its owner"):
        load_settings()


def _clear_env(monkeypatch):
    monkeypatch.delenv("MINIFLUX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIFLUX_API_TOKEN", raising=False)


def _write_conf(text, mode=0o600):
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def test_load_settings_strips_only_matching_quotes(monkeypatch):
    _clear_env(monkeypatch)
    _write_conf(
        "MINIFLUX_BASE_URL='http://localhost:8080'\nMINIFLUX_API_TOKEN=\"tok'\n"
    )

    settings = load_settings()
    assert settings.base_url == "http://localhost:8080"
    assert settings.api_token == "\"tok'"


def test_load_settings_rejects_config_file_owned_by_another_user(monkeypatch):
    _clear_env(monkeypatch)
    _write_conf("MINIFLUX_API_TOKEN=from-file\n")
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)

    with pytest.raises(ConfigError, match="not owned by the user"):
        load_settings()


def test_load_settings_rejects_non_regular_config_path(monkeypatch):
    _clear_env(monkeypatch)
    config_file_path().mkdir(parents=True)

    with pytest.raises(ConfigError):
        load_settings()


def test_load_settings_rejects_fifo_without_blocking(monkeypatch):
    _clear_env(monkeypatch)
    path = config_file_path()
    path.parent.mkdir(parents=True)
    os.mkfifo(path, 0o600)

    with pytest.raises(ConfigError, match="not a regular file"):
        load_settings()


def test_load_settings_rejects_world_readable_config_file(monkeypatch):
    _clear_env(monkeypatch)
    _write_conf("MINIFLUX_API_TOKEN=from-file\n", mode=0o604)

    with pytest.raises(ConfigError, match="chmod 600"):
        load_settings()


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="root bypasses file modes"
)
def test_load_settings_reports_unreadable_config_file(monkeypatch):
    _clear_env(monkeypatch)
    _write_conf("MINIFLUX_API_TOKEN=from-file\n", mode=0o000)

    with pytest.raises(ConfigError, match="Could not open"):
        load_settings()


def test_load_settings_ignores_blank_and_malformed_config_lines(monkeypatch):
    _clear_env(monkeypatch)
    _write_conf(
        "\n  \nnot-a-setting\nMINIFLUX_BASE_URL = http://localhost:8080\nMINIFLUX_API_TOKEN=t\n"
    )

    settings = load_settings()
    assert settings.base_url == "http://localhost:8080"
    assert settings.api_token == "t"


def test_config_file_path_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert (
        config_file_path()
        == tmp_path / ".config" / "miniflux-mcp" / "miniflux-mcp.conf"
    )


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
