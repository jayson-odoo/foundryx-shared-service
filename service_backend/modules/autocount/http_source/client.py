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
from typing import Any, Deque, Dict, List, Optional, Tuple

import httpx

from app.integrations.masking import mask_payload

from ..client import CallRecord
from ..http_client import OpenProbeError, assert_autocount_base_url_deliverable
from ..payloads import bound_payload, mark_truncated

logger = logging.getLogger("foundryx.autocount")

# AC-10-85 (live-replay Finding 1, 2026-09-20) - was 30.0. Measured live:
# db2's `/itembypage` never returned a single successful response at ANY
# page size within the old 30s ceiling (300 rows -> ~65s per plan Appendix
# A7). This is now only the FALLBACK for a connection with no
# `requestTimeoutSeconds` of its own (a legacy row, or one never opened in
# the wizard) - readers of a connection's own value go through
# ``connection_sizing`` below first (`provider.py`'s `pageSize`/
# `requestTimeoutSeconds` fields, 50-1000 / up to 100).
DEFAULT_TIMEOUT_SECONDS = 90.0
# Bounds the in-memory buffer, like ``AutoCountClient.MAX_BUFFERED_CALLS`` -
# a full product walk is ~12 pages; generous headroom, never unbounded.
MAX_BUFFERED_CALLS = 200

# The page size a WALK itself requests when nothing on the connection
# overrides it - the source's OWN choice, never the vendor's cap (AC-08-22
# "1000 requested, the echoed PageSize/TotalPages trusted"). Lives here
# (rather than only in `source.py`, its sole pre-confirm-3 reader) so
# `connection_sizing` below can share it with `preview.py`.
DEFAULT_PAGE_SIZE = 1000
# AC-10-75's halving floor - also the low end of the `pageSize` connection
# field's own save-time range (`provider.py`'s `PAGE_SIZE_FIELD_MIN`).
MIN_PAGE_SIZE = 50


def connection_sizing(config: Optional[Dict[str, Any]]) -> Tuple[int, float]:
    """AC-10-85 / sprint-5/10 confirm-3 S1 - the ONE reader of an
    ``autocount`` open-REST connection's own ``pageSize``/
    ``requestTimeoutSeconds`` (wire-shaped strings, e.g. ``"250"``),
    returning ``(page_size, timeout_seconds)``. Shared by every caller that
    used to read these independently (``http_source.source.HttpApiSource.
    __init__`` for a real run; ``http_source.preview.run_http_preview`` via
    ``services.etl_service.EtlService.preview_http``/``preview_http_columns``
    for a Test-button sample) so a preview and a real run against the SAME
    connection always agree on both knobs - previously the preview silently
    ignored the connection's ``requestTimeoutSeconds`` entirely and always
    built its client at the bare module default.

    ``page_size`` is CLAMPED to ``MIN_PAGE_SIZE..DEFAULT_PAGE_SIZE``;
    ``timeout_seconds`` falls back to ``DEFAULT_TIMEOUT_SECONDS`` for a
    blank/missing/unparsable/non-positive value - a stored row is never
    trusted outright (a legacy row written before either field existed, or
    a 0/negative value hand-edited into the table, must not ask the
    wrapper for nothing or fail every request instantly)."""
    cfg = config or {}

    page_raw = str(cfg.get("pageSize") or "").strip()
    if page_raw:
        try:
            page_size = max(MIN_PAGE_SIZE, min(int(page_raw), DEFAULT_PAGE_SIZE))
        except (TypeError, ValueError):
            page_size = DEFAULT_PAGE_SIZE
    else:
        page_size = DEFAULT_PAGE_SIZE

    timeout_raw = str(cfg.get("requestTimeoutSeconds") or "").strip()
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if timeout_raw:
        try:
            timeout_value = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_value = DEFAULT_TIMEOUT_SECONDS
        if timeout_value > 0:
            timeout_seconds = timeout_value

    return page_size, timeout_seconds

# AC-10-08 - an explicit, honest User-Agent on every open-REST request.
# Cloudflare 403s the default python-urllib UA, and the default httpx UA
# (``python-httpx/<version>``) is not something to depend on either. This
# restates the module's own ``manifest.json`` version (there is no DB/tenant
# context here to look up the per-tenant INSTALLED version via
# ``app.dependencies.module_version``) - keep it in sync on every bump.
USER_AGENT = "Foundryx-AutoCount-ESB/0.11.0"


class HttpTransportError(Exception):
    """The host could not be reached, or timed out. Distinct from an HTTP
    status the server actually answered.

    ``is_timeout`` (AC-10-75) tells the retry ladder in ``source.py`` which
    of the two bounded-retry policies applies: a TIMEOUT (incl. how a
    Cloudflare 524 is CLASSIFIED, not raised here - that arrives as an
    ordinary 200-range-failing response) gets exactly one retry before the
    page-size-halving decision; a connect error or another 5xx gets up to
    two retries with a longer backoff and never halves.
    """

    def __init__(self, message: str, *, is_timeout: bool = False):
        super().__init__(message)
        self.message = message
        self.is_timeout = is_timeout


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
        json`` and this client's own ``timeout_seconds`` (AC-08-23; the
        connection's ``requestTimeoutSeconds``, else
        ``DEFAULT_TIMEOUT_SECONDS`` - AC-10-85). Buffers a ``CallRecord`` on
        both the success and the transport-failure path.

        AC-10-58 M2 - the outbound SSRF guard is re-run immediately before
        EVERY request this way (the main walk, every lookup, and the preview
        sample all route through this one method) - never only once at
        connection save, since DNS can be re-pointed afterwards. A blocked
        target never reaches ``self._client.get`` at all; it raises the SAME
        ``HttpTransportError`` a genuine unreachable host would, so every
        existing caller (the retry ladder, the preview route's field-named
        error) handles it without a new branch."""
        started = time.monotonic()
        try:
            assert_autocount_base_url_deliverable(self.base_url)
        except OpenProbeError as exc:
            self._record_call(path, params, None, started, error=f"blocked: {exc.message}")
            raise HttpTransportError(exc.message, is_timeout=False) from exc
        url = f"{self.base_url}{path}"
        try:
            response = self._client.get(
                url,
                params=params,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            self._record_call(path, params, None, started, error=f"timeout: {exc}")
            raise HttpTransportError(
                f"{self.base_url}{path} did not respond within "
                f"{self.timeout_seconds:g}s.",
                is_timeout=True,
            ) from exc
        except httpx.HTTPError as exc:
            self._record_call(
                path, params, None, started, error=f"{type(exc).__name__}: {exc}"
            )
            raise HttpTransportError(
                f"Could not reach {self.base_url}{path} ({type(exc).__name__}).",
                is_timeout=False,
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
