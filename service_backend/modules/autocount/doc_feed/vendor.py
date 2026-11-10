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

import httpx

from ..http_source.client import HttpApiClient, HttpTransportError
from ..http_source.envelope import ENVELOPE_PAGED, parse_page
from ..http_source.source import (
    CLOUDFLARE_TIMEOUT_STATUS,
    MAX_TIMEOUT_ATTEMPTS_PER_PAGE,
    TIMEOUT_RETRY_BACKOFF_SECONDS,
    TRANSPORT_RETRY_BACKOFFS_SECONDS,
)
from .clock import yyyymmdd
from .constants import BY_DOC_DATE_PATH, BY_LAST_MODIFIED_PATH

VENDOR_TRANSPORT = "VENDOR_TRANSPORT"
VENDOR_HTTP = "VENDOR_HTTP"
VENDOR_NOT_JSON = "VENDOR_NOT_JSON"
VENDOR_SHAPE = "VENDOR_SHAPE"
VENDOR_PAGED = "VENDOR_PAGED"


class DocFeedVendorError(Exception):
    """One vendor GET failed. ``code`` is one of the ``VENDOR_*`` constants
    above - the run row's own ``errorCode`` (AC-14-12)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class DocFeedVendor:
    """One feed connection's vendor reads. ``client`` is an already-built
    ``HttpApiClient`` (base URL + timeout + optional test transport)."""

    def __init__(self, client: HttpApiClient) -> None:
        self._client = client

    # ── document doors (plain arrays, V2) ────────────────────────────────────

    def day_by_last_modified(self, feed: str, day) -> List[Dict[str, Any]]:
        path = BY_LAST_MODIFIED_PATH[feed]
        return self._document_day(path, {"lastModified": yyyymmdd(day)})

    def day_by_doc_date(self, feed: str, day) -> List[Dict[str, Any]]:
        path = BY_DOC_DATE_PATH[feed]
        return self._document_day(path, {"DocDate": yyyymmdd(day)})

    def get_day(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Any registered day door (sprint-5/17 doc finder) - the SAME retry
        ladder and plain-array parse the two feed doors above use."""
        return self._document_day(path, params)

    def _document_day(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                response = self._client.get(path, params)
            except HttpTransportError as exc:
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
