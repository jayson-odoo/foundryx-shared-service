"""Paged vs list ENVELOPE classification for the open REST API (AC-08-22).

Every confirmed endpoint answers one of two shapes: a dict carrying ``Data``
(a paged master/document list, e.g. ``/itembypage``) or a bare JSON array (a
lookup list, e.g. ``/location``). The shape is established once from the
FIRST page and held for the rest of the walk - a later page answering the
OTHER shape is server-side drift, not data, and fails the run (AC-08-23);
this module only classifies, it never guesses or repairs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ENVELOPE_PAGED = "paged"
ENVELOPE_LIST = "list"


@dataclass(frozen=True)
class EnvelopePage:
    kind: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    page: Optional[int] = None
    total_pages: Optional[int] = None
    total_count: Optional[int] = None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_page(body: Any) -> EnvelopePage:
    """Classify ONE response body.

    Raises ``ValueError`` (the caller wraps it into ``HttpSourceError``) on a
    shape that is neither a paged envelope nor a bare array.
    """
    if isinstance(body, dict) and "Data" in body:
        data = body.get("Data")
        if not isinstance(data, list):
            raise ValueError("the 'Data' field was not a JSON array")
        return EnvelopePage(
            kind=ENVELOPE_PAGED,
            rows=[row for row in data if isinstance(row, dict)],
            page=_as_int(body.get("Page")),
            total_pages=_as_int(body.get("TotalPages")),
            total_count=_as_int(body.get("TotalCount")),
        )
    if isinstance(body, list):
        return EnvelopePage(
            kind=ENVELOPE_LIST,
            rows=[row for row in body if isinstance(row, dict)],
        )
    raise ValueError(
        "the response was neither a paged envelope ({Data: [...]}) nor a "
        "JSON array"
    )
