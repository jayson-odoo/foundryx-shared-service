"""The one class that writes to AutoCount (plan 55 section 6b, AC-55-01..05).

POST / PUT / DELETE, JSON body, the allowlist guard re-run before every request,
the house SSRF-guarded transport with redirects off, and never a retry (a
``DtlKey 0`` row would be added twice). A path never carries a query string; the
one door that needs one (plan 61 cancel, ``DELETE /Cancel<Doc>bydocno?DocNo=``)
goes through ``delete_query``, which lets httpx encode the parameters. Every
request (and every request the guard refuses) is one ``ac_api_call_log`` row when
the caller attached a ``CallLog`` (plan 61 section 4.8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import httpx

from app.services.url_guard import UrlGuardError

from modules.autocount.http_client import autocount_guarded_client
from modules.autocount.write_back import auth, call_log as cl
from modules.autocount.write_back.guard import WriteNotAllowed, assert_write_allowed


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


def _parse_text(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


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
        self._call_log: Optional[cl.CallLog] = None
        self._auth_headers: Dict[str, str] = {}
        self._secrets: Tuple[str, ...] = ()

    def set_auth_headers(self, headers: Mapping[str, str]) -> None:
        """The optional API key header this client sends on every request (plan 63); never logged."""
        self._auth_headers = dict(headers)
        self._secrets: Tuple[str, ...] = tuple(getattr(headers, "secrets", ()))

    def attach_call_log(self, log: "cl.CallLog") -> None:
        """Every request from now on writes one row to ``log`` (plan 61 section 4.8)."""
        self._call_log = log

    def post(self, path: str, body: Any) -> WriteResponse:
        return self._send("POST", path, body)

    def put(self, path: str, body: Any) -> WriteResponse:
        return self._send("PUT", path, body)

    def delete(self, path: str, body: Any) -> WriteResponse:
        return self._send("DELETE", path, body)

    def delete_query(self, path: str, params: Mapping[str, str]) -> WriteResponse:
        """DELETE with NO body and ``params`` as the query string, each value
        URL-encoded by httpx (a ``/``, ``&``, ``#`` or ``?`` in a value can never
        change the path or add a parameter)."""
        return self._send("DELETE", path, None, params={str(k): str(v) for k, v in params.items()})

    def _http(self) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            )
        return autocount_guarded_client(self._timeout)

    def _send(
        self, method: str, path: str, body: Any, *, params: Optional[Mapping[str, str]] = None
    ) -> WriteResponse:
        started = self._call_log.started() if self._call_log else None
        sent_path = path if params is None else str(httpx.URL(path, params=dict(params)))
        try:
            assert_write_allowed(self.base_url)
        except WriteNotAllowed as exc:  # refused before sending: logged, nothing sent
            self._log(method, sent_path, body, started, None, None, cl.GUARD_REFUSED, exc.code)
            raise
        _check_path(path)
        url = self.base_url.rstrip("/") + path
        try:
            with self._http() as http:
                if params is not None:
                    request = http.build_request(method, url, params=dict(params), headers=self._auth_headers)
                else:
                    request = http.build_request(method, url, json=body, headers=self._auth_headers)
                sent_path = cl.vendor_path(self.base_url, request.url.raw_path.decode("ascii"))
                response = http.send(request)
        except httpx.TimeoutException:
            self._log(method, sent_path, body, started, None, None, cl.TIMEOUT, "WRITE_TIMEOUT")
            raise WriteTransportError("WRITE_TIMEOUT") from None
        except (httpx.HTTPError, httpx.InvalidURL, UrlGuardError):
            self._log(method, sent_path, body, started, None, None, cl.CONNECT_ERROR, "WRITE_CONNECT")
            raise WriteTransportError("WRITE_CONNECT") from None
        text = auth.mask(response.text, self._secrets) if self._secrets else response.text
        self._log(method, sent_path, body, started, response.status_code, text,
                  cl.OK if response.is_success else cl.HTTP_ERROR, None)
        return WriteResponse(
            status_code=response.status_code,
            body=_parse_text(text) if self._secrets else _parse_body(response),
            ok=response.is_success,
        )

    def _log(self, method: str, path: str, body: Any, started: Any, status: Optional[int],
             text: Optional[str], outcome: str, code: Optional[str]) -> None:
        if self._call_log is None or started is None:
            return
        self._call_log.record(base_url=self.base_url, method=method, path=path, started=started,
                              request_json=body, status=status, body=text, outcome=outcome, error_code=code)
