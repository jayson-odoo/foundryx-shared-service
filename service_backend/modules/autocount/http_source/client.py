"""``HttpApiClient`` - the paged GET transport a real HTTP-task run walks
against, page after page.

Distinct from ``http_client.py`` (the tiny single-GET no-auth PROBE used by
the provider Test button and open-company onboarding): this is the
workhorse a run uses repeatedly, buffering ONE ``CallRecord`` per request -
masked then bounded, the exact same order ``client.AutoCountClient.
_record_call`` uses, and for the same reason (a truncation preview must
never carry a secret the mask would have caught). There is nothing to mask
on this unauthenticated wrapper today; the seam is here so an eventual
API-key header (BL-SS-202) is a field, not a rewrite.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import httpx

from app.integrations.masking import mask_payload

from ..client import CallRecord
from ..payloads import bound_payload, mark_truncated

logger = logging.getLogger("foundryx.autocount")

DEFAULT_TIMEOUT_SECONDS = 30.0
# Bounds the in-memory buffer, like ``AutoCountClient.MAX_BUFFERED_CALLS`` -
# a full product walk is ~12 pages; generous headroom, never unbounded.
MAX_BUFFERED_CALLS = 200


class HttpTransportError(Exception):
    """The host could not be reached, or timed out. Distinct from an HTTP
    status the server actually answered."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class HttpApiClient:
    """One task's paged GET client. ``transport``, when given, is a FULL
    ``httpx.Client`` used as-is (house convention, see ``client_from_
    connection``)."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: Optional[httpx.Client] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._owns_transport = transport is None
        self._calls: Deque[CallRecord] = deque(maxlen=MAX_BUFFERED_CALLS)

    @property
    def _client(self) -> httpx.Client:
        if self._transport is None:
            # S5 (sprint-5/08 review round 1) - never silently follow a
            # redirect off the configured base URL (SSRF-adjacent).
            self._transport = httpx.Client(
                timeout=self.timeout_seconds, follow_redirects=False
            )
        return self._transport

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def get(self, path: str, params: Dict[str, Any]) -> httpx.Response:
        """One ``GET {base_url}{path}?params`` with ``Accept: application/
        json`` and a 30s timeout (AC-08-23). Buffers a ``CallRecord`` on
        both the success and the transport-failure path."""
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        try:
            response = self._client.get(
                url,
                params=params,
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            self._record_call(path, params, None, started, error=f"timeout: {exc}")
            raise HttpTransportError(
                f"{self.base_url}{path} did not respond within "
                f"{self.timeout_seconds:g}s."
            ) from exc
        except httpx.HTTPError as exc:
            self._record_call(
                path, params, None, started, error=f"{type(exc).__name__}: {exc}"
            )
            raise HttpTransportError(
                f"Could not reach {self.base_url}{path} ({type(exc).__name__})."
            ) from exc
        self._record_call(path, params, response, started)
        return response

    def _record_call(
        self,
        path: str,
        params: Dict[str, Any],
        response: Optional[httpx.Response],
        started: float,
        *,
        error: Optional[str] = None,
    ) -> None:
        try:
            latency_ms = int((time.monotonic() - started) * 1000)
            status_code = response.status_code if response is not None else None
            ok = status_code is not None and 200 <= status_code < 300 and error is None

            body: Any = None
            row_count: Optional[int] = None
            if response is not None:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text[:200]
                if isinstance(body, dict):
                    data = body.get("Data")
                    if isinstance(data, list):
                        row_count = len(data)
                elif isinstance(body, list):
                    row_count = len(body)

            query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
            display_path = f"{path}?{query}" if query else path

            request_payload, request_truncated = bound_payload(
                {
                    "method": "GET",
                    "url": f"{self.base_url}{path}",
                    "params": mask_payload(dict(params or {})),
                }
            )
            #     !!  S10 (sprint-5/08 review round 1) - NEVER PERSIST ROW
            #         BODIES FOR THIS CLIENT.  !!
            # The wrapper is public and unauthenticated (plan §2.10): a
            # debtor page carries phone numbers and credit limits, a product
            # page carries pricing. ``mask_payload``/``bound_payload`` only
            # protect known CREDENTIAL keys and cap byte size - they do
            # nothing about ordinary business PII sitting in an open
            # `Data[]` array, and `MAX_LIST_ITEMS` (5) would still have let
            # up to 5 rows of it land in ``integration_activity`` on every
            # page. So the response side of THIS client's activity record
            # carries COUNTERS ONLY (status/rowCount/envelope) - never the
            # body. The SQL/vendor client (`client.py`'s own
            # `_record_call`) is untouched: that transport is never public.
            envelope: Optional[str] = None
            if isinstance(body, dict) and isinstance(body.get("Data"), list):
                envelope = "paged"
            elif isinstance(body, list):
                envelope = "list"
            response_summary = {
                "statusCode": status_code,
                "rowCount": row_count,
                "envelope": envelope,
            }

            self._calls.append(
                CallRecord(
                    method="GET",
                    path=display_path,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    ok=ok,
                    request=mark_truncated(
                        request_payload
                        if isinstance(request_payload, dict)
                        else {"body": request_payload},
                        request_truncated,
                    ),
                    response=response_summary,
                    error_message=(str(mask_payload(error))[:1000] if error else None),
                )
            )
        except Exception:  # noqa: BLE001 - observability NEVER breaks a call
            logger.exception(
                "failed to buffer an AutoCount HTTP call record for %s", path
            )

    def record_note(self, message: str, *, ok: bool = True) -> None:
        """Append a synthetic, no-request ``CallRecord`` carrying an
        observability note (S12, sprint-5/08 review round 1) - drained
        through the EXACT SAME ``drain_calls()`` path as a genuine page
        fetch, so something worth surfacing on a run (the page-drift
        duplicate-key warning, AC-08-22) reaches ``integration_activity``
        instead of only ``logger.warning``, which nobody but a developer
        with shell access ever sees."""
        try:
            self._calls.append(
                CallRecord(
                    method="NOTE",
                    path=self.base_url,
                    status_code=None,
                    latency_ms=0,
                    ok=ok,
                    request={},
                    response={"message": str(mask_payload(message))[:1000]},
                    error_message=None,
                )
            )
        except Exception:  # noqa: BLE001 - observability NEVER breaks a run
            logger.exception("failed to buffer an AutoCount HTTP note")

    def drain_calls(self) -> List[CallRecord]:
        drained = list(self._calls)
        self._calls.clear()
        return drained
