"""``DocFeedVendor`` (D7, D8, D18, D19) - the four quoted vendor GET doors.

Reuses ``HttpApiClient`` (SSRF re-check per request, pinned User-Agent) and
``envelope.parse_page``; the retry ladder mirrors
``http_source.source.HttpApiSource._fetch_page`` byte-for-byte (a timeout
gets one retry after 1s; a connect error / 5xx / 524 gets up to
``len(TRANSPORT_RETRY_BACKOFFS_SECONDS)`` retries with a longer backoff, no
halving - a document GET is a single small page, never large enough
to need page-size halving).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ..http_source import gentle
from ..http_source.client import HttpApiClient, HttpTransportError
from ..http_source.envelope import ENVELOPE_PAGED, parse_page
from ..http_source.source import (
    CLOUDFLARE_TIMEOUT_STATUS,
    MAX_TIMEOUT_ATTEMPTS_PER_PAGE,
    TIMEOUT_RETRY_BACKOFF_SECONDS,
    TRANSPORT_RETRY_BACKOFFS_SECONDS,
)
from .clock import yyyymmdd
from .constants import BY_DOC_DATE_PARAM, BY_DOC_DATE_PATH, BY_LAST_MODIFIED_PATH

VENDOR_TRANSPORT = "VENDOR_TRANSPORT"
VENDOR_HTTP = "VENDOR_HTTP"
VENDOR_NOT_JSON = "VENDOR_NOT_JSON"
VENDOR_SHAPE = "VENDOR_SHAPE"
VENDOR_PAGED = "VENDOR_PAGED"
# AUTOCOUNT-LOAD-STRATEGY - the server's safety stop is on; nothing was sent.
VENDOR_STOPPED = "VENDOR_STOPPED"


class DocFeedVendorError(Exception):
    """One vendor GET failed. ``code`` is one of the ``VENDOR_*`` constants
    above - the run row's own ``errorCode`` (AC-14-12)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class DocFeedVendor:
    """One feed connection's vendor reads. ``client`` is an already-built
    ``HttpApiClient`` (base URL + timeout + optional test transport)."""

    def __init__(self, client: HttpApiClient, *, pacing: Optional[gentle.GentleSettings] = None) -> None:
        self._client = client
        self._call_log = None
        # AUTOCOUNT-LOAD-STRATEGY - the pause between two day reads: the
        # connection's own "Pause between pages" floor, longer while
        # AutoCount answers slowly. ``None`` (a caller that reads one day
        # only) = never pause.
        self._pacer = (
            gentle.AdaptivePause(
                floor_seconds=pacing.page_pause_seconds, slow_seconds=pacing.slow_page_seconds,
            )
            if pacing is not None else None
        )
        self._reads = 0

    def pace(self, *, should_stop=None) -> bool:
        """Call before each day read: pauses after the first read, adapting
        to how fast the last one was answered. ``False`` = stopped during
        the pause."""
        if self._pacer is None or self._reads == 0:
            return True
        seconds = self._pacer.after_page(self._client.last_latency_seconds)
        if seconds <= 0:
            return True
        return gentle.sleep_between_pages(seconds, should_stop=should_stop)

    def attach_call_log(self, log) -> None:
        """Plan 72 (contract 2.15 section 1, UAC S0-1) - from now on every GET
        attempt also writes one ``ac_api_call_log`` row (``write_back.call_log``,
        the logged reader's own log): the vendor path + query as sent, the
        status and the capped body; never the host or a header."""
        self._call_log = log

    def _logged_get(self, path: str, params: Dict[str, Any]) -> httpx.Response:
        if self._call_log is None:
            return self._client.get(path, params)
        from ..write_back import call_log as cl

        started = self._call_log.started()
        sent = f"{path}?{urlencode(params)}" if params else path
        base_url = self._client.base_url
        try:
            response = self._client.get(path, params)
        except HttpTransportError as exc:
            self._call_log.record(
                base_url=base_url, method="GET", path=sent, started=started,
                outcome=cl.TIMEOUT if exc.is_timeout else cl.CONNECT_ERROR,
                error_code=VENDOR_TRANSPORT,
            )
            raise
        ok = 200 <= response.status_code < 300
        self._call_log.record(
            base_url=base_url, method="GET", path=sent, started=started,
            status=response.status_code, body=response.text,
            outcome=cl.OK if ok else cl.HTTP_ERROR, error_code=None if ok else VENDOR_HTTP,
        )
        return response

    # ── document doors (plain arrays, V2) ────────────────────────────────────

    def day_by_last_modified(self, feed: str, day) -> List[Dict[str, Any]]:
        path = BY_LAST_MODIFIED_PATH[feed]
        return self._document_day(path, {"lastModified": yyyymmdd(day)})

    def day_by_doc_date(self, feed: str, day) -> List[Dict[str, Any]]:
        # Plan 72 - ``ProjectRegbyDate`` takes ``Date``, the document doors ``DocDate``.
        path = BY_DOC_DATE_PATH[feed]
        return self._document_day(path, {BY_DOC_DATE_PARAM[feed]: yyyymmdd(day)})

    def get_day(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Any registered day door (sprint-5/17 doc finder) - the SAME retry
        ladder and plain-array parse the two feed doors above use."""
        return self._document_day(path, params)

    def _document_day(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._reads += 1
        response = self._fetch_with_retry(path, params)
        body = self._as_json(response)
        parsed = self._as_page(body)
        if parsed.kind == ENVELOPE_PAGED:
            raise DocFeedVendorError(
                VENDOR_PAGED,
                f"'{path}' unexpectedly answered a paged envelope; document "
                "doors must answer a plain array (V2).",
            )
        return parsed.rows

    # ── shared retry + parse ─────────────────────────────────────────────────

    def _fetch_with_retry(self, path: str, params: Dict[str, Any]) -> httpx.Response:
        timeout_attempts = 0
        transport_attempts = 0
        while True:
            try:
                response = self._logged_get(path, params)
            except HttpTransportError as exc:
                if exc.stopped_until is not None or exc.busy:
                    raise DocFeedVendorError(VENDOR_STOPPED, exc.message) from exc
                if exc.is_timeout:
                    timeout_attempts += 1
                    if timeout_attempts >= MAX_TIMEOUT_ATTEMPTS_PER_PAGE:
                        raise DocFeedVendorError(VENDOR_TRANSPORT, exc.message) from exc
                    time.sleep(TIMEOUT_RETRY_BACKOFF_SECONDS)
                    continue
                transport_attempts += 1
                if transport_attempts > len(TRANSPORT_RETRY_BACKOFFS_SECONDS):
                    raise DocFeedVendorError(VENDOR_TRANSPORT, exc.message) from exc
                time.sleep(TRANSPORT_RETRY_BACKOFFS_SECONDS[transport_attempts - 1])
                continue

            if response.status_code == CLOUDFLARE_TIMEOUT_STATUS:
                timeout_attempts += 1
                if timeout_attempts >= MAX_TIMEOUT_ATTEMPTS_PER_PAGE:
                    raise DocFeedVendorError(
                        VENDOR_HTTP, f"AutoCount answered HTTP {response.status_code}."
                    )
                time.sleep(TIMEOUT_RETRY_BACKOFF_SECONDS)
                continue
            if response.status_code >= 500:
                transport_attempts += 1
                if transport_attempts > len(TRANSPORT_RETRY_BACKOFFS_SECONDS):
                    raise DocFeedVendorError(
                        VENDOR_HTTP, f"AutoCount answered HTTP {response.status_code}."
                    )
                time.sleep(TRANSPORT_RETRY_BACKOFFS_SECONDS[transport_attempts - 1])
                continue
            if not (200 <= response.status_code < 300):
                raise DocFeedVendorError(
                    VENDOR_HTTP, f"AutoCount answered HTTP {response.status_code}."
                )
            return response

    @staticmethod
    def _as_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise DocFeedVendorError(
                VENDOR_NOT_JSON, "The vendor response was not JSON."
            ) from exc

    @staticmethod
    def _as_page(body: Any):
        try:
            return parse_page(body)
        except ValueError as exc:
            raise DocFeedVendorError(VENDOR_SHAPE, str(exc)) from exc
