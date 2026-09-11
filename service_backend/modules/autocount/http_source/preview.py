"""Page-1 sample preview for the open REST API (AC-08-14) - the Source tab's
Test button AND ``POST /autocount/http/preview``.

Deliberately a SINGLE request, never a walk: ``pageSize=50`` for a paged
envelope (or the first 50 rows of a bare array) is enough to show the
envelope shape, the column names and a sample - proving the endpoint is
reachable and shaped as expected without paying for a full extract.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .client import HttpApiClient, HttpTransportError
from .envelope import parse_page

PREVIEW_PAGE_SIZE = 50


class HttpPreviewError(Exception):
    """A preview failed. ``field`` names which input to blame (AC-08-14:
    ``connectionId`` for a bad connection, ``path`` for a 404/timeout/non-JSON)."""

    def __init__(self, message: str, *, field: str = "path") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class HttpPreviewResult:
    envelope: str
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    total_count: Optional[int] = None
    duration_ms: int = 0


def run_http_preview(
    base_url: str,
    path: str,
    *,
    distinct_of: Optional[List[str]] = None,
    transport: Optional[httpx.Client] = None,
) -> HttpPreviewResult:
    client = HttpApiClient(base_url, transport=transport)
    started = time.monotonic()
    try:
        try:
            response = client.get(path, {"page": 1, "pageSize": PREVIEW_PAGE_SIZE})
        except HttpTransportError as exc:
            raise HttpPreviewError(exc.message, field="path") from exc

        if not (200 <= response.status_code < 300):
            raise HttpPreviewError(
                f"AutoCount answered HTTP {response.status_code} for '{path}'.",
                field="path",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise HttpPreviewError(
                f"The response for '{path}' was not JSON.", field="path"
            ) from exc
        try:
            parsed = parse_page(body)
        except ValueError as exc:
            raise HttpPreviewError(str(exc), field="path") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        rows = parsed.rows[:PREVIEW_PAGE_SIZE]

        if distinct_of:
            seen: set = set()
            values: List[str] = []
            for row in rows:
                for field_name in distinct_of:
                    raw_value = row.get(field_name)
                    if raw_value is None:
                        continue
                    value = str(raw_value).strip()
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    values.append(value)
            return HttpPreviewResult(
                envelope=parsed.kind,
                columns=["value"],
                rows=[{"value": v} for v in values],
                total_count=parsed.total_count,
                duration_ms=duration_ms,
            )

        columns: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in columns:
                    columns.append(key)

        return HttpPreviewResult(
            envelope=parsed.kind,
            columns=columns,
            rows=rows,
            total_count=parsed.total_count,
            duration_ms=duration_ms,
        )
    finally:
        client.close()
