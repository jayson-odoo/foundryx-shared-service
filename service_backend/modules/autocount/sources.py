"""``EntitySource`` - the fetch seam (D6, plan §6), plus the AutoCount GRN
implementation.

Pluggability sits on the axis of **uncertainty**: how data is fetched (two API
generations coexist, and each customer runs their own wrapper version).
Endpoint topology is NOT uncertain - it is a fixed uniform grammar
(``POST /api/{Entity}/Get{Entity}``) - so there is no seam there.

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
from .envelopes import ENVELOPE_STATUS_DICT, envelope_for
from .mapping import read_path

logger = logging.getLogger("foundryx.autocount")

# ── initial-load policy (D3 / AC-14-25) ───────────────────────────────────────
#
#     !!  A LOOKBACK WINDOW IS CORRECT FOR DOCUMENTS AND WRONG FOR MASTERS.  !!
#
# A document stream (GRN) is naturally time-bounded, so reaching back N days is
# the right first read. A MASTER LIST is a standing set whose purpose is to
# mirror current state - applying document semantics to it produces a sync that
# reports success while importing ~1% of the data, which is the most dangerous
# failure available because nothing looks wrong.
#
# Measured live 2026-07-21 against slice 1's 30-day default: Creditor 106 total →
# **1** in window; Debtor 172 → **2**. A 365-day window still misses 4 and 15.
# So no window is correct for masters - only an unbounded first pull.
#
# ``initial_lookback_days`` therefore applies to ``windowed`` entities ONLY.
INITIAL_LOAD_FULL = "full"
INITIAL_LOAD_WINDOWED = "windowed"
INITIAL_LOADS = (INITIAL_LOAD_FULL, INITIAL_LOAD_WINDOWED)


class UnknownInitialLoad(Exception):
    """A configured ``initial_load`` is not one we implement. LOUD - silently
    defaulting to ``windowed`` would give a master entity a 30-day first read and
    report the resulting 1-of-106 import as a clean success."""


class TruncatedWindowError(AutoCountError):
    """The record cap was reached, so the window MAY be truncated and we cannot
    prove otherwise (AC-13-17 / AC-13-46).

    ``len == cap`` is the ONLY truncation signal the vendor gives us. The
    response's per-record ``"N of TOTAL"`` marker looks like a free total and is
    not one - TOTAL is computed AFTER the cap is applied (verified live: an
    uncapped fetch reports ``"1 of 11"``, a ``RecordCount:5`` fetch reports
    ``"1 of 5"``). Trusting it would turn a truncated page into a "complete" one.
    """


@dataclass(frozen=True)
class Watermark:
    """The delta position for one (company, entity)."""

    last_modified_at: Optional[datetime] = None
    cursor: Optional[Dict[str, Any]] = None

    def start(self, *, lookback_days: int, now: Optional[datetime] = None) -> datetime:
        """Window start for a **windowed** entity: the watermark, or a bounded
        first-run lookback.

        For a document stream a missing watermark must NEVER mean "fetch
        everything" - an unbounded first fetch on a customer with years of
        history is guaranteed to hit the record cap and fail.

        This stays the WINDOWED rule only. A ``full`` entity never calls it: the
        decision to send no lower bound belongs to the source, which knows the
        entity's ``initial_load`` - a ``Watermark`` is a value object and has no
        business holding policy (see ``AutoCountReadSource.window``).
        """
        if self.last_modified_at is not None:
            return self.last_modified_at.astimezone(timezone.utc)
        return (now or datetime.now(timezone.utc)) - timedelta(days=lookback_days)


@dataclass
class SourceRecord:
    """One raw vendor record + its parsed ``LastModified``.

    The RAW payload travels with it all the way to storage (AC-13-07) -
    retained so a field discovered later can be mapped retroactively without
    re-fetching history.
    """

    raw: Dict[str, Any]
    last_modified: Optional[datetime] = None


@dataclass
class FetchResult:
    records: List[SourceRecord] = field(default_factory=list)
    # Max LastModified observed. The caller advances the watermark to this ONLY
    # once the whole batch has succeeded - never here.
    max_last_modified: Optional[datetime] = None
    # ``None`` = no lower bound was sent: the unbounded initial master load.
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None
    # What the vendor says is available, when it says so (AC-14-26). Reported
    # NEXT TO the fetched count so an operator can tell "nothing changed" from
    # "the window excluded almost everything". Advisory ONLY - slice 1 verified
    # this marker is computed AFTER the record cap is applied, so it is never
    # used to decide truncation.
    reported_total: Optional[int] = None


class EntitySource(Protocol):
    """One entity, one company. Returns records changed since the watermark."""

    entity_type: str

    def fetch_changes(self, since: Watermark) -> FetchResult: ...


class AutoCountReadSource:
    """The vendor read implementation: ``POST /api/{Entity}/Get{Entity}`` with
    ``LastModifiedFrom``/``To`` (verified live to genuinely filter).

    **Header and all lines arrive in ONE call** (AC-13-06) - the vendor nests
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
        envelope: str = ENVELOPE_STATUS_DICT,
        initial_load: str = INITIAL_LOAD_WINDOWED,
        identifier_key: str = "DocNo",
        last_modified_path: str = "LastModified",
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.client = client
        self.entity_type = entity_type
        self.vendor_entity = vendor_entity
        self.record_cap = record_cap
        self.lookback_days = lookback_days
        # Per-entity from config (AC-14-03) - resolved HERE so a bad value fails
        # at construction with a clear message, not mid-fetch.
        self.envelope = envelope_for(envelope)
        if initial_load not in INITIAL_LOADS:
            raise UnknownInitialLoad(
                f"'{initial_load}' is not a known initial-load policy for "
                f"AutoCount. Expected one of: {', '.join(INITIAL_LOADS)}."
            )
        self.initial_load = initial_load
        self.identifier_key = identifier_key
        # Masters nest the stamp at ``Data.0.LastModified``; documents carry it
        # at the top level. Wrong here = the window assertion fails every row AND
        # the watermark never advances.
        self.last_modified_path = last_modified_path
        self._now = now_fn

    def window(self, since: Watermark) -> Tuple[Optional[datetime], datetime]:
        """The window to request. ``start=None`` means **no lower bound**.

        That happens exactly once per entity: a ``full`` entity with no watermark
        yet (AC-14-25). Every subsequent run has a watermark and proceeds as a
        normal delta, so ``full`` costs one unbounded read, not a permanent one.
        """
        now = self._now()
        if since.last_modified_at is None and self.initial_load == INITIAL_LOAD_FULL:
            return None, now
        return since.start(lookback_days=self.lookback_days, now=now), now

    def fetch_changes(self, since: Watermark) -> FetchResult:
        start, end = self.window(since)
        unbounded = start is None

        # build_read_filter enforces the list-valued identifier keys - the exact
        # mistake AutoCount does NOT report (it silently returns the whole
        # table). client.read then asserts the returned window (AC-13-04a).
        payload = build_read_filter(
            record_count=self.record_cap,
            last_modified_from=start,
            # An unbounded initial load sends NEITHER bound. Sending only a
            # lower-less upper bound would be a filter we cannot verify: there is
            # no window to assert the result against, so it would buy nothing and
            # risk the wrapper interpreting a half-specified range.
            last_modified_to=None if unbounded else end,
            identifier_key=self.identifier_key,
        )
        unwrapped = self.client.read(
            self.vendor_entity,
            payload,
            # No lower bound means no window to assert - correct, not a gap:
            # AC-13-04a's defence exists to catch a filter the server IGNORED,
            # and here we deliberately sent none.
            window=None if unbounded else (start, end),
            envelope=self.envelope,
            last_modified_path=self.last_modified_path,
        )
        raw_records = unwrapped.records

        if len(raw_records) >= self.record_cap:
            # No silent caps (AC-13-46): log the bound AND fail. Window
            # narrowing lands in slice 2 (AC-13-16).
            described = (
                "the unbounded initial load"
                if unbounded
                else f"window {start.isoformat()}..{end.isoformat()}"
            )
            logger.error(
                "AutoCount %s fetch hit the record cap (%d) for %s - the page may "
                "be truncated and window narrowing is not yet implemented; failing "
                "rather than delivering partial data.",
                self.vendor_entity,
                self.record_cap,
                described,
            )
            # The remedy differs by policy, so the message must too: you cannot
            # "narrow the window" of a load that deliberately has none.
            remedy = (
                "Raise the record cap for this entity."
                if unbounded
                else "Narrow the window or raise the record cap."
            )
            raise TruncatedWindowError(
                f"AutoCount returned {len(raw_records)} {self.vendor_entity} records, "
                f"reaching the record cap of {self.record_cap} for {described}. The "
                f"result may be truncated, so no data was accepted and the watermark "
                f"was not advanced. {remedy}"
            )

        records: List[SourceRecord] = []
        max_seen: Optional[datetime] = None
        for raw in raw_records:
            # Per-entity path: masters keep the stamp in the NESTED row.
            stamp = parse_last_modified(read_path(raw, self.last_modified_path))
            records.append(SourceRecord(raw=raw, last_modified=stamp))
            if stamp is not None and (max_seen is None or stamp > max_seen):
                max_seen = stamp

        return FetchResult(
            records=records,
            max_last_modified=max_seen,
            window_from=start,
            window_to=end,
            reported_total=unwrapped.reported_total,
        )


# ── source registry (D6) ──────────────────────────────────────────────────────
# ``ac_entity_config.source_impl`` selects the implementation PER ENTITY, PER
# COMPANY. A second API generation, or a customer needing a bespoke fetch, adds
# a factory here and a config value - no change to the pipeline.

SourceFactory = Callable[..., EntitySource]

_SOURCES: Dict[str, SourceFactory] = {}


class UnknownSourceImpl(Exception):
    """A configured ``source_impl`` has no registered factory. LOUD - a silent
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
    envelope: str = ENVELOPE_STATUS_DICT,
    initial_load: str = INITIAL_LOAD_WINDOWED,
    identifier_key: str = "DocNo",
    last_modified_path: str = "LastModified",
) -> EntitySource:
    return AutoCountReadSource(
        client,
        entity_type=entity_type,
        vendor_entity=vendor_entity,
        record_cap=record_cap,
        lookback_days=lookback_days,
        envelope=envelope,
        initial_load=initial_load,
        identifier_key=identifier_key,
        last_modified_path=last_modified_path,
    )


register_source("autocount_read", _autocount_read_factory)
