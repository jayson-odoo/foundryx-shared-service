"""SS-STOCK-BAL-SOOTHE - keep the open REST wrapper's load low and even
(``documentation/plans/sprint-5/ss-stock-bal-soothe.md``).

Three per-connection knobs, all ON by default (a connection saved before
this lane carries none of the keys and gets the defaults):

* ``pagePauseSeconds`` - a pause between two page requests of one walk, so a
  69-page stock walk is a trickle instead of a burst.
* ``stockSkipWhenUnchanged`` + ``stockFullWalkMinutes`` - a scheduled stock
  run first reads the byLastModified day lists (DO, GRN, SO, PO); no document
  modified since the last full walk started means the walk is skipped, but a
  full walk always runs once the last one is ``stockFullWalkMinutes`` old.
* ``lookupCacheMinutes`` - a scheduled stock run reuses the item / item-UOM
  lookup rows of the last verified walk for this long (BL-SS-353).

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

STOCK_SKIP_FIELD_DEFAULT = "yes"

STOCK_FULL_WALK_FIELD_DEFAULT = 60
STOCK_FULL_WALK_FIELD_MIN = 5
STOCK_FULL_WALK_FIELD_MAX = 1440

LOOKUP_CACHE_FIELD_DEFAULT = 60
LOOKUP_CACHE_FIELD_MIN = 0
LOOKUP_CACHE_FIELD_MAX = 1440

# The day doors read before a scheduled stock walk, stock movers first so a
# busy day usually stops after the first GET.
STOCK_PROBE_PATHS: Tuple[str, ...] = (
    "/deliveryorderbyLastModified",
    "/goodsreceivenotebyLastModified",
    "/salesorderbyLastModified",
    "/purchaseorderbyLastModified",
)
# More days than this since the last full walk -> walk (no long probe).
STOCK_PROBE_MAX_DAYS = 3
# Clock-skew margin: a document stamped up to this long BEFORE the last walk
# started still counts as a change.
STOCK_PROBE_MARGIN_SECONDS = 120


@dataclass(frozen=True)
class GentleSettings:
    page_pause_seconds: float
    skip_when_unchanged: bool
    full_walk_minutes: int
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
    """The ONE reader of the four keys. A stored value is never trusted
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

    skip_raw = str(cfg.get("stockSkipWhenUnchanged") or STOCK_SKIP_FIELD_DEFAULT).strip().lower()
    return GentleSettings(
        page_pause_seconds=pause,
        skip_when_unchanged=skip_raw != "no",
        full_walk_minutes=_int_in_range(
            cfg.get("stockFullWalkMinutes"), STOCK_FULL_WALK_FIELD_DEFAULT,
            STOCK_FULL_WALK_FIELD_MIN, STOCK_FULL_WALK_FIELD_MAX,
        ),
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
    skip_raw = str(cfg.get("stockSkipWhenUnchanged") or "").strip().lower()
    if skip_raw and skip_raw not in ("yes", "no"):
        return "stockSkipWhenUnchanged must be yes or no."
    for key, low, high in (
        ("stockFullWalkMinutes", STOCK_FULL_WALK_FIELD_MIN, STOCK_FULL_WALK_FIELD_MAX),
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
    expires_at: float


_monotonic = time.monotonic
_lock = threading.Lock()
_cache: Dict[Tuple[str, ...], CachedLookup] = {}


def lookup_cache_key(tenant_id: str, connection_id: str, base_url: str, path: str) -> Tuple[str, ...]:
    return (str(tenant_id), str(connection_id), str(base_url), str(path))


def get_cached_lookup(key: Tuple[str, ...]) -> Optional[CachedLookup]:
    now = _monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        if now >= hit.expires_at:
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
        _cache[key] = CachedLookup(
            rows=rows, reported_total=reported_total, envelope_kind=envelope_kind,
            stored_at=now, expires_at=now + ttl_minutes * 60,
        )


def clear_lookup_cache() -> None:
    with _lock:
        _cache.clear()
