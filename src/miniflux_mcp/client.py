"""Read-only HTTP client for the Miniflux REST API.

This module exposes exactly one way to talk to Miniflux: `get_json`, which
issues a GET request. There is no method here, public or private, that can
perform a POST, PUT, PATCH, or DELETE, so a bug elsewhere in this codebase
cannot escalate into a write against the Miniflux instance.
"""

from __future__ import annotations

import json
from typing import Any, Self

import httpx

from .config import Settings


class MinifluxError(RuntimeError):
    """Raised for any failure talking to Miniflux.

    Messages are hand-written and never include the API token or request
    headers, even when wrapping an underlying httpx exception.
    """


class ResponseTooLargeError(MinifluxError):
    """Raised when a Miniflux response exceeds the configured size cap."""


class MinifluxClient:
    def __init__(
        self, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._base_url = settings.base_url
        self._max_bytes = settings.max_response_bytes
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds),
            headers={"X-Auth-Token": settings.api_token},
            # Redirects could otherwise be used to steer a request (and the
            # auth token in its headers) at a host we never validated.
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a single GET request and return the parsed JSON body."""
        url = f"{self._base_url}{path}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            with self._client.stream("GET", url, params=clean_params) as response:
                self._check_status(response)
                body = self._read_bounded(response)
        except httpx.TimeoutException as exc:
            raise MinifluxError(f"Request to Miniflux timed out: {path}") from exc
        except httpx.TransportError as exc:
            raise MinifluxError(f"Could not reach Miniflux: {path}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise MinifluxError(
                f"Miniflux returned a non-JSON response for {path}"
            ) from exc

    def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise ResponseTooLargeError(
                    f"Miniflux response exceeded the {self._max_bytes}-byte limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise MinifluxError("Miniflux rejected the API token (401 Unauthorized)")
        if status == 403:
            raise MinifluxError(
                "Miniflux denied access to this resource (403 Forbidden)"
            )
        if status == 404:
            raise MinifluxError("Miniflux resource not found (404)")
        if 300 <= status < 400:
            raise MinifluxError(
                f"Miniflux attempted a redirect (status {status}); refusing to follow it"
            )
        if status >= 400:
            raise MinifluxError(f"Miniflux request failed with status {status}")
