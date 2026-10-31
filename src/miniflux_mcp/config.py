"""Runtime configuration, loaded once from environment variables or a config file.

The API token and base URL are read here and only here. No tool accepts
either as an argument, so a malicious or buggy MCP client cannot redirect
requests to a different host or exfiltrate the token through a tool call.

MINIFLUX_BASE_URL and MINIFLUX_API_TOKEN can each come from an environment
variable or from a KEY=VALUE fallback file (see config_file_path()); an
env var always wins when both are set.
"""

from __future__ import annotations

import ipaddress
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000
CONFIG_FILE_RELATIVE_PATH = Path("miniflux-mcp") / "miniflux-mcp.conf"

Transport = Literal["stdio", "http"]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    # repr=False: dataclass auto-repr would otherwise print the token in
    # full wherever this object lands in a traceback or debug log.
    api_token: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_base_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ConfigError("MINIFLUX_BASE_URL must start with http:// or https://")
    if not parts.hostname:
        raise ConfigError("MINIFLUX_BASE_URL must include a host")
    if parts.username or parts.password:
        raise ConfigError("MINIFLUX_BASE_URL must not contain embedded credentials")
    if parts.scheme == "http" and not is_loopback_host(parts.hostname):
        raise ConfigError(
            f"Refusing plain http:// for non-loopback host {parts.hostname!r}; "
            "use https:// for anything that is not localhost"
        )
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")


def config_file_path() -> Path:
    """Where the fallback KEY=VALUE config file lives, honoring XDG_CONFIG_HOME."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return config_home / CONFIG_FILE_RELATIVE_PATH


def _parse_conf_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _read_config_file(path: Path) -> dict[str, str]:
    """Read the optional fallback config file, refusing anything but a private regular file.

    Checks type, owner, and permissions on the same open file descriptor used
    for the read, so there is no window between the check and the read where
    the path could be swapped for a different file (TOCTOU). O_NONBLOCK keeps
    a FIFO planted at the path from hanging startup before it can be
    rejected. Env vars still take precedence in load_settings(), so a secrets
    manager injecting MINIFLUX_API_TOKEN at process start continues to work
    unchanged; this file only fills in whatever an env var didn't supply.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"Could not open {path}: {exc.strerror}") from exc

    try:
        _check_config_file(path, os.fstat(fd))
        handle = os.fdopen(fd, encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        return _parse_conf_file(handle.read())


def _check_config_file(path: Path, info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"{path} is not a regular file")
    if os.name != "posix":
        return
    if info.st_uid != os.getuid():
        raise ConfigError(f"{path} is not owned by the user running this server")
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(
            f"{path} is readable by users other than its owner; "
            f"run `chmod 600 {path}` before storing a token in it"
        )


def load_settings() -> Settings:
    path = config_file_path()
    file_values = _read_config_file(path)

    def _get(name: str) -> str:
        return os.environ.get(name, "").strip() or file_values.get(name, "").strip()

    base_url = _get("MINIFLUX_BASE_URL")
    api_token = _get("MINIFLUX_API_TOKEN")

    if not base_url:
        raise ConfigError(
            f"MINIFLUX_BASE_URL is required: set it as an environment variable "
            f"or in {path}"
        )
    if not api_token:
        raise ConfigError(
            f"MINIFLUX_API_TOKEN is required: set it as an environment variable "
            f"or in {path}"
        )

    return Settings(base_url=_validate_base_url(base_url), api_token=api_token)


@dataclass(frozen=True)
class TransportSettings:
    transport: Transport = "stdio"
    host: str = DEFAULT_HTTP_HOST
    port: int = DEFAULT_HTTP_PORT


def load_transport_settings() -> TransportSettings:
    """Load how the server should be exposed: local stdio, or network HTTP.

    Binding to a non-loopback host requires MINIFLUX_MCP_ALLOW_REMOTE=1, a
    deliberate second step so a HOST override alone can't silently expose
    the server to a network it wasn't meant to reach.
    """
    transport = os.environ.get("MINIFLUX_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in ("stdio", "http"):
        raise ConfigError("MINIFLUX_MCP_TRANSPORT must be 'stdio' or 'http'")

    if transport == "stdio":
        return TransportSettings(transport="stdio")

    host = os.environ.get("MINIFLUX_MCP_HOST", DEFAULT_HTTP_HOST).strip()
    port_raw = os.environ.get("MINIFLUX_MCP_PORT", str(DEFAULT_HTTP_PORT)).strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(
            f"MINIFLUX_MCP_PORT must be an integer, got {port_raw!r}"
        ) from exc
    if not (1 <= port <= 65535):
        raise ConfigError(f"MINIFLUX_MCP_PORT must be between 1 and 65535, got {port}")

    if not is_loopback_host(host):
        allow_remote = os.environ.get("MINIFLUX_MCP_ALLOW_REMOTE", "").strip() == "1"
        if not allow_remote:
            raise ConfigError(
                f"MINIFLUX_MCP_HOST={host!r} is not loopback; set "
                "MINIFLUX_MCP_ALLOW_REMOTE=1 to confirm you intend to expose "
                "this server on the network (every request will still need "
                "to present the Miniflux API token as a Bearer credential)"
            )

    return TransportSettings(transport="http", host=host, port=port)
