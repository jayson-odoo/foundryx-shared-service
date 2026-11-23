"""Record-shape helpers (D8, D18, D19) - DocKey / dedupe / push order /
``source_ref`` / DocDate parsing / ``LastModified`` -> UTC, plus the ONE
unmapped canonical record this feed ever sends (Q1).

Records are read and re-sent exactly as the vendor returned them (D18): no
field is ever renamed, dropped or re-typed. The functions here answer three
questions about a raw vendor dict - "what DocKey is this", "which copy is
newest", "what does the CRM call this record" - never reshape it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from ..canonical.base import CanonicalRecord
from .clock import MYT
from .constants import (
    FEED_DELIVERY_ORDERS,
    FEED_GOODS_RECEIVE_NOTES,
    FEED_PROJECT_REGISTRATIONS,
    PROJNO_FEEDS,
)

# Plan 72 - the date field of a project registration (its by-date door's day).
PROJECT_REG_DATE_FIELD = "Date"


def proj_no(record: Dict[str, Any]) -> Optional[str]:
    """Plan 72 - a registration's ``ProjNo``, trimmed; ``None`` when blank or
    not text (such a record is never sent, counted as ``skippedNoKey``)."""
    value = record.get("ProjNo")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _proj_no_key(record: Dict[str, Any]) -> Optional[int]:
    """Plan 72 - the ledger / issue key of a registration: a stable positive
    63-bit number from its ``ProjNo`` matched as AutoCount does (trimmed,
    case-insensitive), so the BIGINT ``doc_key`` tables hold it unchanged."""
    number = proj_no(record)
    if number is None:
        return None
    digest = hashlib.sha256(number.casefold().encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def doc_key(record: Dict[str, Any], feed: Optional[str] = None) -> Optional[int]:
    """The record's ``DocKey`` as a plain ``int``, or ``None`` when it is
    missing, a bare bool, or not an integer (D19) - such a record is never
    sent (the CRM would answer ``failed`` with a raw/null ``source_ref`` no
    record could be matched back to). A ``ProjNo`` feed (plan 72) keys on
    ``ProjNo`` instead; every other feed ignores ``ProjNo`` (documents carry
    one too)."""
    if feed in PROJNO_FEEDS:
        return _proj_no_key(record)
    value = record.get("DocKey")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("-").isdigit():
            try:
                return int(stripped)
            except ValueError:
                return None
        return None
    return None


def dedupe_latest(
    records: List[Dict[str, Any]], feed: Optional[str] = None
) -> List[Dict[str, Any]]:
    """One record per DocKey - the copy with the greatest ``LastModified``
    (D8). The vendor's own fixed ISO format sorts lexically identically to
    chronological order (plan 08 D7), so this never needs to PARSE the
    timestamp. A record with no DocKey is dropped (``doc_key`` returned
    ``None`` - counted as ``skippedNoKey`` by the caller, never here)."""
    by_key: Dict[int, Dict[str, Any]] = {}
    for record in records:
        key = doc_key(record, feed)
        if key is None:
            continue
        existing = by_key.get(key)
        if existing is None or str(record.get("LastModified") or "") >= str(
            existing.get("LastModified") or ""
        ):
            by_key[key] = record
    return list(by_key.values())


def content_digest(record: Dict[str, Any]) -> str:
    """DOC-FEED-WINDOW - sha256 of the WHOLE vendor record (header and its
    ``Details`` lines) as canonical JSON (sorted keys, so the vendor's own
    key order never reads as a change). A line edit changes it even when
    the header ``LastModified`` did not move."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def push_order(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``LastModified`` ascending (D8) - oldest first, stale-guard friendly."""
    return sorted(records, key=lambda r: str(r.get("LastModified") or ""))


def source_ref(feed: str, book: str, record: Dict[str, Any]) -> str:
    """The CRM's own derivation (13.3 / C2): ``{book}:DO:{DocKey}`` /
    ``{book}:GRN:{DocKey}``. Branches are the regular ``branch`` entity now
    (plan 14 section 11), never a doc feed: an unknown feed raises."""
    if feed == FEED_DELIVERY_ORDERS:
        return f"{book}:DO:{doc_key(record)}"
    if feed == FEED_GOODS_RECEIVE_NOTES:
        return f"{book}:GRN:{doc_key(record)}"
    if feed == FEED_PROJECT_REGISTRATIONS:
        return f"{book}:PROJREG:{proj_no(record)}"
    raise ValueError(f"Unknown doc feed '{feed}'.")


def doc_date(record: Dict[str, Any], feed: Optional[str] = None) -> Optional[date]:
    """Parses ISO date / ISO datetime / ``yyyyMMdd``. ``None`` when
    unparseable - the record is still sent (D19); the CRM fails it and no
    ledger row appears. A registration's day is its ``Date`` (plan 72)."""
    if feed in PROJNO_FEEDS:
        return parse_doc_day(record.get(PROJECT_REG_DATE_FIELD))
    return parse_doc_day(record.get("DocDate"))


def doc_number(record: Dict[str, Any], feed: Optional[str] = None) -> Optional[str]:
    """The number the ledger / issue rows show: ``DocNo``, or the registration's ``ProjNo``."""
    if feed in PROJNO_FEEDS:
        return proj_no(record)
    return record.get("DocNo")


def parse_doc_day(raw: Any) -> Optional[date]:
    """``doc_date``'s parser on its own, for any date-bearing field (the doc
    finder's registry names the field per doc type)."""
    if not raw:
        return None
    text = str(raw)
    try:
        if "T" in text:
            return datetime.fromisoformat(text).date()
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def vendor_modified_at(record: Dict[str, Any]) -> Optional[datetime]:
    """The naive MYT ``LastModified`` converted to an aware-UTC timestamp."""
    raw = record.get("LastModified")
    if not raw:
        return None
    try:
        naive = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return naive.replace(tzinfo=MYT).astimezone(timezone.utc)


class RawVendorRecord(CanonicalRecord):
    """The ONE unmapped canonical record this feed ever sends (Q1, D18):
    ``sink_payload()`` returns the raw vendor dict verbatim, unknown keys and
    ``Details`` included, so the sink's own JSON encoder re-sends exactly
    what was pulled."""

    raw: Dict[str, Any]

    def sink_payload(self) -> Dict[str, Any]:
        if self.entity_type in PROJNO_FEEDS:
            return project_registration_wire(self.raw, self.source_ref)
        return self.raw


def project_registration_wire(raw: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """Plan 72 (contract 2.15 section 3) - a registration as it is pushed:
    every value exactly as AutoCount answered it, plus ``source_ref``, with
    ``Date`` as ``yyyy-mm-dd``. An unparseable ``Date`` is sent as read (the
    CRM refuses that record by itself, D19)."""
    out = dict(raw)
    out["source_ref"] = ref
    day = parse_doc_day(raw.get(PROJECT_REG_DATE_FIELD))
    if day is not None:
        out[PROJECT_REG_DATE_FIELD] = day.isoformat()
    return out
