"""Runtime configuration, loaded once from environment variables.

The API token and base URL are read here and only here. No tool accepts
either as an argument, so a malicious or buggy MCP client cannot redirect
requests to a different host or exfiltrate the token through a tool call.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000

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


def load_settings() -> Settings:
    base_url = os.environ.get("MINIFLUX_BASE_URL", "").strip()
    api_token = os.environ.get("MINIFLUX_API_TOKEN", "").strip()

    if not base_url:
        raise ConfigError("MINIFLUX_BASE_URL environment variable is required")
    if not api_token:
        raise ConfigError("MINIFLUX_API_TOKEN environment variable is required")

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
