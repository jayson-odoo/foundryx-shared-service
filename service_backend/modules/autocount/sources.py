"""``EntitySource`` — the fetch seam (D6, plan §6), plus the AutoCount GRN
implementation.

Pluggability sits on the axis of **uncertainty**: how data is fetched (two API
generations coexist, and each customer runs their own wrapper version).
Endpoint topology is NOT uncertain — it is a fixed uniform grammar
(``POST /api/{Entity}/Get{Entity}``) — so there is no seam there.

Everything downstream of a source (mapping, staging, approval, push, retry,
observability) is identical regardless of which implementation is selected.

Slice-1 paging (AC-13-46 / a deliberate stub for AC-13-16/17): a full page is
detected by ``len(records) == cap`` and **fails LOUDLY**. It is never silently
truncated, and the watermark never advances over a truncated read. Window
narrowing is slice 2; until it exists, a stopped sync an operator can see beats
a running sync that quietly loses documents.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from .canonical.grn import VENDOR_ENTITY
from .client import AutoCountClient, AutoCountError, build_read_filter, parse_last_modified

logger = logging.getLogger("foundryx.autocount")


class TruncatedWindowError(AutoCountError):
    """The record cap was reached, so the window MAY be truncated and we cannot
    prove otherwise (AC-13-17 / AC-13-46).

    ``len == cap`` is the ONLY truncation signal the vendor gives us. The
    response's per-record ``"N of TOTAL"`` marker looks like a free total and is
    not one — TOTAL is computed AFTER the cap is applied (verified live: an
    uncapped fetch reports ``"1 of 11"``, a ``RecordCount:5`` fetch reports
    ``"1 of 5"``). Trusting it would turn a truncated page into a "complete" one.
    """


@dataclass(frozen=True)
class Watermark:
    """The delta position for one (company, entity)."""

    last_modified_at: Optional[datetime] = None
    cursor: Optional[Dict[str, Any]] = None

    def start(self, *, lookback_days: int, now: Optional[datetime] = None) -> datetime:
        """Window start: the watermark, or a bounded first-run lookback.

        A missing watermark must NEVER mean "fetch everything" — an unbounded
        first fetch on a customer with years of history is guaranteed to hit the
        record cap and fail. The initial FULL load is a different problem with a
        different, supervised design (D20).
        """
        if self.last_modified_at is not None:
            return self.last_modified_at.astimezone(timezone.utc)
        return (now or datetime.now(timezone.utc)) - timedelta(days=lookback_days)


@dataclass
class SourceRecord:
    """One raw vendor record + its parsed ``LastModified``.

    The RAW payload travels with it all the way to storage (AC-13-07) —
    retained so a field discovered later can be mapped retroactively without
    re-fetching history.
    """

    raw: Dict[str, Any]
    last_modified: Optional[datetime] = None


@dataclass
class FetchResult:
    records: List[SourceRecord] = field(default_factory=list)
    # Max LastModified observed. The caller advances the watermark to this ONLY
    # once the whole batch has succeeded — never here.
    max_last_modified: Optional[datetime] = None
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None


class EntitySource(Protocol):
    """One entity, one company. Returns records changed since the watermark."""

    entity_type: str

    def fetch_changes(self, since: Watermark) -> FetchResult: ...


class AutoCountReadSource:
    """The vendor read implementation: ``POST /api/{Entity}/Get{Entity}`` with
    ``LastModifiedFrom``/``To`` (verified live to genuinely filter).

    **Header and all lines arrive in ONE call** (AC-13-06) — the vendor nests
    the detail array in the header response, so there is no per-document
    fan-out anywhere. This is the property that makes the whole delta design
    viable at volume.
    """

    def __init__(
        self,
        client: AutoCountClient,
        *,
        entity_type: str,
        vendor_entity: str = VENDOR_ENTITY,
        record_cap: int = 200,
        lookback_days: int = 30,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.client = client
        self.entity_type = entity_type
        self.vendor_entity = vendor_entity
        self.record_cap = record_cap
        self.lookback_days = lookback_days
        self._now = now_fn

    def window(self, since: Watermark) -> Tuple[datetime, datetime]:
        now = self._now()
        return since.start(lookback_days=self.lookback_days, now=now), now

    def fetch_changes(self, since: Watermark) -> FetchResult:
        start, end = self.window(since)

        # build_read_filter enforces the list-valued identifier keys — the exact
        # mistake AutoCount does NOT report (it silently returns the whole
        # table). client.read then asserts the returned window (AC-13-04a).
        payload = build_read_filter(
            record_count=self.record_cap,
            last_modified_from=start,
            last_modified_to=end,
        )
        raw_records = self.client.read(
            self.vendor_entity, payload, window=(start, end)
        )

        if len(raw_records) >= self.record_cap:
            # No silent caps (AC-13-46): log the bound AND fail. Window
            # narrowing lands in slice 2 (AC-13-16).
            logger.error(
                "AutoCount %s fetch hit the record cap (%d) for window %s..%s — "
                "the page may be truncated and window narrowing is not yet "
                "implemented; failing rather than delivering partial data.",
                self.vendor_entity,
                self.record_cap,
                start.isoformat(),
                end.isoformat(),
            )
            raise TruncatedWindowError(
                f"AutoCount returned {len(raw_records)} {self.vendor_entity} records, "
                f"reaching the record cap of {self.record_cap} for the window "
                f"{start.date()}..{end.date()}. The result may be truncated, so no "
                f"data was accepted and the watermark was not advanced. Narrow the "
                f"window or raise the record cap."
            )

        records: List[SourceRecord] = []
        max_seen: Optional[datetime] = None
        for raw in raw_records:
            stamp = parse_last_modified(raw.get("LastModified"))
            records.append(SourceRecord(raw=raw, last_modified=stamp))
            if stamp is not None and (max_seen is None or stamp > max_seen):
                max_seen = stamp

        return FetchResult(
            records=records,
            max_last_modified=max_seen,
            window_from=start,
            window_to=end,
        )


# ── source registry (D6) ──────────────────────────────────────────────────────
# ``ac_entity_config.source_impl`` selects the implementation PER ENTITY, PER
# COMPANY. A second API generation, or a customer needing a bespoke fetch, adds
# a factory here and a config value — no change to the pipeline.

SourceFactory = Callable[..., EntitySource]

_SOURCES: Dict[str, SourceFactory] = {}


class UnknownSourceImpl(Exception):
    """A configured ``source_impl`` has no registered factory. LOUD — a silent
    fallback to the default would sync a customer with the wrong strategy and
    look like it worked."""


def register_source(name: str, factory: SourceFactory) -> None:
    _SOURCES[name] = factory


def source_factory(name: str) -> SourceFactory:
    factory = _SOURCES.get(name)
    if factory is None:
        raise UnknownSourceImpl(
            f"No AutoCount source implementation registered for '{name}'."
        )
    return factory


def _autocount_read_factory(
    client: AutoCountClient,
    *,
    entity_type: str,
    vendor_entity: str = VENDOR_ENTITY,
    record_cap: int = 200,
    lookback_days: int = 30,
) -> EntitySource:
    return AutoCountReadSource(
        client,
        entity_type=entity_type,
        vendor_entity=vendor_entity,
        record_cap=record_cap,
        lookback_days=lookback_days,
    )


register_source("autocount_read", _autocount_read_factory)
