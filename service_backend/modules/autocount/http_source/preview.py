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

# Path length ceiling shared by every caller that accepts an operator-typed
# endpoint path (AC-08-13's task-save validator AND the preview route
# itself, S4 sprint-5/08 review round 1 - the preview route used to apply
# NONE of these rules, so a `..`/query-string/over-long path reached the
# vendor call unchecked).
MAX_PATH_LENGTH = 200


def validate_http_path(path: str) -> Optional[str]:
    """The one shared rule set for an operator-typed HTTP task path
    (AC-08-13): must start with ``/``, no ``..`` (traversal), no ``?``
    (page params are ours), <= 200 chars. Returns an operator-safe message,
    or ``None`` when the path is clean. A blank path is NOT this function's
    job (callers differ on whether blank is even reachable / how to word
    "required" - `_validate_http_config` phrases it as "Enter the endpoint
    path.", the preview route as "Enter a path to preview.")."""
    if not path.startswith("/"):
        return "The path must start with '/'."
    if ".." in path:
        return "The path may not contain '..'."
    if "?" in path:
        return "The path may not include a query string - page params are ours."
    if len(path) > MAX_PATH_LENGTH:
        return f"The path is too long ({MAX_PATH_LENGTH} characters max)."
    return None


class HttpPreviewError(Exception):
    """A preview failed. ``field`` names which input to blame (AC-08-14:
    ``connectionId`` for a bad connection, ``path`` for a 404/timeout/non-JSON)."""

    def __init__(self, message: str, *, field: str = "path") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class LookupPreviewCount:
    """One lookup's Test-time result (AC-10-05): how many of the sampled
    rows matched vs missed against it."""

    alias: str
    matched: int
    missed: int


@dataclass
class HttpPreviewResult:
    envelope: str
    # ``columns`` - the WIRE response shape, unchanged by review round 1b:
    # raw columns AND every merged lookup alias, in row-insertion order.
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    total_count: Optional[int] = None
    duration_ms: int = 0
    # sprint-5/10 (AC-10-05) - per-lookup {alias, matched, missed} counts,
    # empty when the request carried none.
    lookups: List[LookupPreviewCount] = field(default_factory=list)
    # review round 1b - the RAW main-endpoint columns ONLY, captured BEFORE
    # any lookup merges anything onto the sample. This is what the caller
    # (``EtlService.preview_http``) now stores as the task's
    # ``result_columns`` - aliases are derived at read time
    # (``lookups.effective_result_columns``), never stored, so a save-time
    # collision check against the stored value is exact with no carve-out.
    raw_columns: List[str] = field(default_factory=list)
    # sprint-5/10 S5a follow-up (AC-10-82) - the generic funnel counters
    # (``rowsIn``/``excludedCount``/``groups``/``droppedByRule``/``rowsOut``/
    # ``roundedCount``), set by ``EtlService.preview_http`` ONLY when the
    # request carried a ``combine`` block; ``None`` otherwise, so a plain
    # preview's response is unaffected. ``rows``/``columns`` above are
    # overwritten with the COMBINED shape in that same case (AC-10-80 - the
    # push path itself runs combine before hashing, so the preview grid
    # must show what a real run would produce, not the pre-combine sample).
    combine_funnel: Optional[Dict[str, Any]] = None
    # review round 5 (R5-A) - the PRE-combine column set (raw + lookup
    # aliases + computed aliases), set by ``EtlService.preview_http`` ONLY
    # alongside ``combine_funnel`` above - ``None`` for a plain preview.
    pre_combine_columns: Optional[List[str]] = None


def run_http_preview(
    base_url: str,
    path: str,
    *,
    distinct_of: Optional[List[str]] = None,
    lookups: Optional[List[Dict[str, Any]]] = None,
    transport: Optional[httpx.Client] = None,
) -> HttpPreviewResult:
    # Local import (AC-10-05) - ``http_source.lookups`` imports
    # ``validate_http_path`` FROM this module at ITS OWN top level, so a
    # module-level import back here would cycle.
    from .lookups import AliasCollisionError, build_index, merge_onto_rows

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
                raw_columns=["value"],
            )

        # review round 1 blocker 2(i) - PREVIEW holds the raw main-endpoint
        # columns before any lookup has merged anything onto the sample;
        # this is the ONE place that can tell a genuine raw column apart
        # from an alias with total certainty, so an alias (a lookup's own
        # ``as`` or any ``fields[].as``) equal to one is an unconditional
        # 422 here - no carve-out, unlike the save-time gate, which cannot
        # always distinguish the two (AC-10-05's own stamped columns).
        # review round 1b - also captured, ORDERED, as ``raw_columns`` -
        # what ``EtlService.preview_http`` now stores as ``result_columns``.
        raw_columns_ordered: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in raw_columns_ordered:
                    raw_columns_ordered.append(key)
        raw_columns = set(raw_columns_ordered)
        for i, spec in enumerate(lookups or []):
            as_name = spec.get("as")
            if isinstance(as_name, str) and as_name in raw_columns:
                raise HttpPreviewError(
                    f"'{as_name}' is already a source column.", field=f"lookups[{i}].as"
                )
            for j, field_spec in enumerate(spec.get("fields") or []):
                if not isinstance(field_spec, dict):
                    continue
                alias = field_spec.get("as")
                if isinstance(alias, str) and alias in raw_columns:
                    raise HttpPreviewError(
                        f"'{alias}' is already a source column.",
                        field=f"lookups[{i}].fields[{j}].as",
                    )

        # AC-10-05 - lookups applied IN ORDER over the sampled page, so the
        # returned columns (and per-lookup counts) match what a real run
        # would merge onto every row.
        lookup_counts: List[LookupPreviewCount] = []
        for i, spec in enumerate(lookups or []):
            lookup_path = str(spec.get("path") or "")
            alias_name = str(spec.get("as") or "")
            try:
                lookup_response = client.get(
                    lookup_path, {"page": 1, "pageSize": PREVIEW_PAGE_SIZE}
                )
            except HttpTransportError as exc:
                raise HttpPreviewError(
                    f"The '{alias_name}' lookup endpoint '{lookup_path}' failed: "
                    f"{exc.message}",
                    field=f"lookups[{i}].path",
                ) from exc
            if not (200 <= lookup_response.status_code < 300):
                raise HttpPreviewError(
                    f"The '{alias_name}' lookup endpoint '{lookup_path}' answered "
                    f"HTTP {lookup_response.status_code}.",
                    field=f"lookups[{i}].path",
                )
            try:
                lookup_body = lookup_response.json()
            except ValueError as exc:
                raise HttpPreviewError(
                    f"The '{alias_name}' lookup endpoint '{lookup_path}' did not "
                    f"answer JSON.",
                    field=f"lookups[{i}].path",
                ) from exc
            try:
                lookup_parsed = parse_page(lookup_body)
            except ValueError as exc:
                raise HttpPreviewError(str(exc), field=f"lookups[{i}].path") from exc

            on = spec.get("on") or []
            fields = spec.get("fields") or []
            # should-fix 8 (review round 1) - cap the lookup probe rows the
            # SAME way the main path is capped a few lines up; a server
            # that ignores `pageSize` must not blow the preview's cost open.
            index = build_index(lookup_parsed.rows[:PREVIEW_PAGE_SIZE], on)
            try:
                misses = merge_onto_rows(rows, index, on, fields)
            except AliasCollisionError as exc:
                # Belt and suspenders - the raw-column check above and the
                # pre-network `validate_lookups` call already catch every
                # reachable case; this never fires in practice.
                raise HttpPreviewError(
                    f"'{exc.alias}' would overwrite an existing column.",
                    field=f"lookups[{i}].fields",
                ) from exc
            lookup_counts.append(
                LookupPreviewCount(
                    alias=alias_name, matched=len(rows) - misses, missed=misses
                )
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
            lookups=lookup_counts,
            raw_columns=raw_columns_ordered,
        )
    finally:
        client.close()
