"""SS-STOCK-BAL-SOOTHE - keep the open REST wrapper's load low and even
(``documentation/plans/sprint-5/ss-stock-bal-soothe.md``).

Two per-connection knobs, both ON by default (a connection saved before
this lane carries neither key and gets the defaults):

* ``pagePauseSeconds`` - a pause between two page requests of one walk, so a
  70-page stock walk is a trickle instead of a burst.
* ``lookupCacheMinutes`` - a scheduled stock run reuses the item / item-UOM
  lookup rows of the last verified walk for this long (BL-SS-353).

Every scheduled stock run still walks the balance endpoint in full (owner
26 Nov: transfers, write-offs and adjustments move stock without any
DO/GRN/SO/PO, so "no document changed" is never a reason to skip).

The lookup cache lives in the worker process (no table): each worker
process walks a lookup at most once per TTL.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

PAGE_PAUSE_FIELD_DEFAULT = 1.0
PAGE_PAUSE_FIELD_MIN = 0.0
PAGE_PAUSE_FIELD_MAX = 10.0

LOOKUP_CACHE_FIELD_DEFAULT = 60
LOOKUP_CACHE_FIELD_MIN = 0
LOOKUP_CACHE_FIELD_MAX = 1440


@dataclass(frozen=True)
class GentleSettings:
    page_pause_seconds: float
    lookup_cache_minutes: int


def _int_in_range(raw: Any, default: int, low: int, high: int) -> int:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def gentle_settings(config: Optional[Dict[str, Any]]) -> GentleSettings:
    """The ONE reader of the two keys. A stored value is never trusted
    outright: blank/junk falls back to the default, a pause past the max is
    clamped to the max."""
    cfg = config or {}

    pause = PAGE_PAUSE_FIELD_DEFAULT
    pause_raw = str(cfg.get("pagePauseSeconds") if cfg.get("pagePauseSeconds") is not None else "").strip()
    if pause_raw:
        try:
            pause = min(max(float(pause_raw), PAGE_PAUSE_FIELD_MIN), PAGE_PAUSE_FIELD_MAX)
        except (TypeError, ValueError):
            pause = PAGE_PAUSE_FIELD_DEFAULT

    return GentleSettings(
        page_pause_seconds=pause,
        lookup_cache_minutes=_int_in_range(
            cfg.get("lookupCacheMinutes"), LOOKUP_CACHE_FIELD_DEFAULT,
            LOOKUP_CACHE_FIELD_MIN, LOOKUP_CACHE_FIELD_MAX,
        ),
    )


def validate_gentle_config(config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Save-time check, naming the field (``provider.validate_config``)."""
    cfg = config or {}
    pause_raw = str(cfg.get("pagePauseSeconds") if cfg.get("pagePauseSeconds") is not None else "").strip()
    if pause_raw:
        try:
            pause = float(pause_raw)
        except ValueError:
            return "pagePauseSeconds must be a number."
        if not (PAGE_PAUSE_FIELD_MIN <= pause <= PAGE_PAUSE_FIELD_MAX):
            return (
                f"pagePauseSeconds must be between {PAGE_PAUSE_FIELD_MIN:g} and "
                f"{PAGE_PAUSE_FIELD_MAX:g}."
            )
    for key, low, high in (
        ("lookupCacheMinutes", LOOKUP_CACHE_FIELD_MIN, LOOKUP_CACHE_FIELD_MAX),
    ):
        raw = str(cfg.get(key) if cfg.get(key) is not None else "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            return f"{key} must be a whole number."
        if not (low <= value <= high):
            return f"{key} must be between {low} and {high}."
    return None


def sleep_between_pages(seconds: float) -> None:
    """The ONE place a walk pauses between pages (tests stub this name)."""
    if seconds > 0:
        time.sleep(seconds)


# ── lookup cache (BL-SS-353) ─────────────────────────────────────────────


@dataclass(frozen=True)
class CachedLookup:
    rows: List[Dict[str, Any]]
    reported_total: Optional[int]
    envelope_kind: Optional[str]
    stored_at: float


_monotonic = time.monotonic
MAX_ENTRY_AGE_SECONDS = LOOKUP_CACHE_FIELD_MAX * 60
_lock = threading.Lock()
_cache: Dict[Tuple[str, ...], CachedLookup] = {}


def lookup_cache_key(tenant_id: str, connection_id: str, base_url: str, path: str) -> Tuple[str, ...]:
    return (str(tenant_id), str(connection_id), str(base_url), str(path))


def get_cached_lookup(key: Tuple[str, ...], *, ttl_minutes: int) -> Optional[CachedLookup]:
    """The entry for ``key`` when it is younger than the CURRENT ``ttl_minutes``
    (so lowering the setting takes effect on the very next run)."""
    if ttl_minutes <= 0:
        return None
    now = _monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        if now - hit.stored_at >= ttl_minutes * 60:
            _cache.pop(key, None)
            return None
        return hit


def store_cached_lookup(
    key: Tuple[str, ...],
    rows: List[Dict[str, Any]],
    reported_total: Optional[int],
    envelope_kind: Optional[str],
    *,
    ttl_minutes: int,
) -> None:
    if ttl_minutes <= 0:
        return
    now = _monotonic()
    with _lock:
        # Sweep entries no run has read for a day (a changed path / base URL /
        # deleted connection would otherwise stay for the process lifetime).
        stale = [k for k, v in _cache.items() if now - v.stored_at >= MAX_ENTRY_AGE_SECONDS]
        for k in stale:
            _cache.pop(k, None)
        _cache[key] = CachedLookup(
            rows=rows, reported_total=reported_total, envelope_kind=envelope_kind,
            stored_at=now,
        )


def clear_lookup_cache() -> None:
    with _lock:
        _cache.clear()
