"""The one class that writes to AutoCount (plan 55 section 6b, AC-55-01..05).

POST / PUT only, JSON body, the allowlist guard re-run before every request,
the house SSRF-guarded transport with redirects off, and never a retry (a
``DtlKey 0`` row would be added twice).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.services.url_guard import UrlGuardError

from modules.autocount.http_client import autocount_guarded_client
from modules.autocount.write_back.guard import assert_write_allowed


@dataclass(frozen=True)
class WriteResponse:
    status_code: int
    body: Any
    ok: bool


class WriteTransportError(Exception):
    """The request did not complete. Text carries only the code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _check_path(path: str) -> None:
    if not path.startswith("/") or ".." in path or "?" in path:
        raise ValueError("Invalid write path.")


def _parse_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


class AutoCountWriteClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 90.0,
    ) -> None:
        assert_write_allowed(base_url)
        self.base_url = base_url
        self._transport = transport
        self._timeout = timeout

    def post(self, path: str, body: Any) -> WriteResponse:
        return self._send("POST", path, body)

    def put(self, path: str, body: Any) -> WriteResponse:
        return self._send("PUT", path, body)

    def _http(self) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            )
        return autocount_guarded_client(self._timeout)

    def _send(self, method: str, path: str, body: Any) -> WriteResponse:
        assert_write_allowed(self.base_url)
        _check_path(path)
        url = self.base_url.rstrip("/") + path
        try:
            with self._http() as http:
                response = http.request(method, url, json=body)
        except httpx.TimeoutException:
            raise WriteTransportError("WRITE_TIMEOUT") from None
        except (httpx.HTTPError, httpx.InvalidURL, UrlGuardError):
            raise WriteTransportError("WRITE_CONNECT") from None
        return WriteResponse(
            status_code=response.status_code,
            body=_parse_body(response),
            ok=response.is_success,
        )
