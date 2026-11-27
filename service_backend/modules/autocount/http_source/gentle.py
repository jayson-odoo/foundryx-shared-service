"""SS-STOCK-BAL-SOOTHE - keep the open REST wrapper's load low and even
(``documentation/plans/sprint-5/ss-stock-bal-soothe.md``).

Two per-connection knobs (a connection saved before this lane carries
neither key and gets the defaults):

* ``pagePauseSeconds`` - a pause between two page requests of one walk, so a
  70-page stock walk is a trickle instead of a burst. SS-STOCK-PAGE-PAUSE-
  CONFIG (owner 27 Nov): the owner sets it, 0-90 s, default 0 ("then you
  let me control"). The pause sleeps in ``PAUSE_SLICE_SECONDS`` slices and
  asks ``should_stop`` between them, so a stopped run never sits it out.
* ``lookupCacheMinutes`` - a scheduled stock run reuses the item / item-UOM
  lookup rows of the last verified walk for this long (BL-SS-353).

Every scheduled stock run still walks the balance endpoint in full (owner
26 Nov: transfers, write-offs and adjustments move stock without any
DO/GRN/SO/PO, so "no document changed" is never a reason to skip).

The lookup cache lives in the worker process (no table): each worker
process walks a lookup at most once per TTL.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

PAGE_PAUSE_FIELD_DEFAULT = 0.0
PAGE_PAUSE_FIELD_MIN = 0.0
# Crew 27 Nov: capped at 90 s so a ~70-page stock run stays under the 2 h job
# limit (``background_job_soft_time_limit_seconds``).
PAGE_PAUSE_FIELD_MAX = 90.0
PAGE_PAUSE_INVALID_MESSAGE = (
    "Pause between pages must be a number from 0 to 90 seconds "
    "(max 90 s: longer pauses make the stock run exceed its 2 h limit)."
)

# One slice of a pause: between slices the run beats its heartbeat and checks
# for a stop (abort / orphan sweep / abandoned build).
PAUSE_SLICE_SECONDS = 5.0
# ``HttpSourceError.code`` of a walk stopped during a pause.
PAUSE_STOPPED_CODE = "stopped"

LOOKUP_CACHE_FIELD_DEFAULT = 60
LOOKUP_CACHE_FIELD_MIN = 0
LOOKUP_CACHE_FIELD_MAX = 1440

# AUTOCOUNT-LOAD-STRATEGY (owner 27 Nov): the vendor says the stock balance
# endpoint can serve 3000 rows a page; every other endpoint (products) stays
# at the connection's own ``pageSize`` (max 1000).
STOCK_PAGE_SIZE_FIELD_DEFAULT = 3000
STOCK_PAGE_SIZE_FIELD_MIN = 50
STOCK_PAGE_SIZE_FIELD_MAX = 3000
# A page slower than this lengthens the pause (``AdaptivePause``); 0 = off.
SLOW_PAGE_FIELD_DEFAULT = 30.0
SLOW_PAGE_FIELD_MIN = 0.0
SLOW_PAGE_FIELD_MAX = 300.0
# The first lengthened pause, when the owner's floor is shorter.
ADAPTIVE_FIRST_PAUSE_SECONDS = 5.0
# Safety stop (``server_gate``): N failed requests in a row stop scheduled
# calls to the server for M minutes. N = 0 switches it off.
STOP_AFTER_FIELD_DEFAULT = 3
STOP_AFTER_FIELD_MIN = 0
STOP_AFTER_FIELD_MAX = 20
STOP_MINUTES_FIELD_DEFAULT = 10
STOP_MINUTES_FIELD_MIN = 1
STOP_MINUTES_FIELD_MAX = 120
ONE_AT_A_TIME_YES = "yes"
ONE_AT_A_TIME_NO = "no"


@dataclass(frozen=True)
class GentleSettings:
    page_pause_seconds: float
    lookup_cache_minutes: int
    stock_page_size: int = STOCK_PAGE_SIZE_FIELD_DEFAULT
    slow_page_seconds: float = SLOW_PAGE_FIELD_DEFAULT


def _int_in_range(raw: Any, default: int, low: int, high: int) -> int:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def _float_in_range(raw: Any, default: float, low: float, high: float) -> float:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and low <= value <= high else default


def gentle_settings(config: Optional[Dict[str, Any]]) -> GentleSettings:
    """The ONE reader of the two keys. A stored value is never trusted
    outright: blank/junk falls back to the default, a pause past the max is
    clamped to the max."""
    cfg = config or {}

    pause = PAGE_PAUSE_FIELD_DEFAULT
    pause_raw = str(cfg.get("pagePauseSeconds") if cfg.get("pagePauseSeconds") is not None else "").strip()
    if pause_raw:
        try:
            value = float(pause_raw)
        except (TypeError, ValueError):
            value = PAGE_PAUSE_FIELD_DEFAULT
        if not math.isfinite(value):
            value = PAGE_PAUSE_FIELD_DEFAULT
        pause = min(max(value, PAGE_PAUSE_FIELD_MIN), PAGE_PAUSE_FIELD_MAX)

    return GentleSettings(
        page_pause_seconds=pause,
        lookup_cache_minutes=_int_in_range(
            cfg.get("lookupCacheMinutes"), LOOKUP_CACHE_FIELD_DEFAULT,
            LOOKUP_CACHE_FIELD_MIN, LOOKUP_CACHE_FIELD_MAX,
        ),
        stock_page_size=_stock_page_size(cfg.get("stockPageSize")),
        slow_page_seconds=_float_in_range(
            cfg.get("slowPageSeconds"), SLOW_PAGE_FIELD_DEFAULT,
            SLOW_PAGE_FIELD_MIN, SLOW_PAGE_FIELD_MAX,
        ),
    )


def _stock_page_size(raw: Any) -> int:
    """Clamped like ``connection_sizing``'s ``pageSize``: a stored value past
    either end is pulled back into range, junk is the default."""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return STOCK_PAGE_SIZE_FIELD_DEFAULT
    try:
        value = int(text)
    except (TypeError, ValueError):
        return STOCK_PAGE_SIZE_FIELD_DEFAULT
    return max(STOCK_PAGE_SIZE_FIELD_MIN, min(value, STOCK_PAGE_SIZE_FIELD_MAX))


def server_policy(config: Optional[Dict[str, Any]]) -> Any:
    """The connection's ``server_gate.ServerPolicy`` (one request at a time,
    safety stop). Junk falls back to the defaults."""
    from .server_gate import ServerPolicy

    cfg = config or {}
    one = str(cfg.get("oneRequestAtATime") or ONE_AT_A_TIME_YES).strip().lower()
    return ServerPolicy(
        one_at_a_time=one != ONE_AT_A_TIME_NO,
        stop_after_failures=_int_in_range(
            cfg.get("stopAfterFailures"), STOP_AFTER_FIELD_DEFAULT,
            STOP_AFTER_FIELD_MIN, STOP_AFTER_FIELD_MAX,
        ),
        stop_minutes=_int_in_range(
            cfg.get("stopMinutes"), STOP_MINUTES_FIELD_DEFAULT,
            STOP_MINUTES_FIELD_MIN, STOP_MINUTES_FIELD_MAX,
        ),
    )


def clean_page_pause(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    """AUTOCOUNT-LOAD-STRATEGY s6 - a task's / document feed's own "Pause
    between pages". ``(None, None)`` = blank (use the connection's value),
    ``(value, None)`` in range, ``(None, message)`` otherwise."""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return None, None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, PAGE_PAUSE_INVALID_MESSAGE
    if not (math.isfinite(value) and PAGE_PAUSE_FIELD_MIN <= value <= PAGE_PAUSE_FIELD_MAX):
        return None, PAGE_PAUSE_INVALID_MESSAGE
    return value, None


def with_own_pause(settings: GentleSettings, own: Any) -> GentleSettings:
    """``settings`` with the task's / feed's own pause in place of the
    connection's, when one is set (a stored value is never trusted outright:
    out of range = the connection's)."""
    value, error = clean_page_pause(own)
    if value is None or error:
        return settings
    from dataclasses import replace

    return replace(settings, page_pause_seconds=value)


class AdaptivePause:
    """The pause before the next page of a walk. Starts at the owner's
    ``pagePauseSeconds`` (the floor). A page slower than ``slow_seconds``
    doubles it (at least ``ADAPTIVE_FIRST_PAUSE_SECONDS``, at most the 90 s
    max); a page faster than half of it halves it back, never below the
    floor. ``slow_seconds`` 0 = always the floor."""

    def __init__(self, *, floor_seconds: float, slow_seconds: float) -> None:
        self.floor = max(0.0, float(floor_seconds))
        self.slow = max(0.0, float(slow_seconds))
        self.seconds = self.floor

    def after_page(self, latency_seconds: Optional[float]) -> float:
        if self.slow <= 0 or latency_seconds is None:
            return self.seconds
        if latency_seconds > self.slow:
            grown = max(self.seconds * 2, ADAPTIVE_FIRST_PAUSE_SECONDS, self.floor)
            self.seconds = min(grown, PAGE_PAUSE_FIELD_MAX)
        elif latency_seconds <= self.slow / 2 and self.seconds > self.floor:
            self.seconds = max(self.seconds / 2, self.floor)
            if self.seconds - self.floor < 0.25:
                self.seconds = self.floor
        return self.seconds


_FIELD_LABELS = {
    "lookupCacheMinutes": "lookupCacheMinutes",
    "stockPageSize": "Stock balance page size",
    "stopAfterFailures": "Stop after failed requests in a row",
    "stopMinutes": "Stop for (minutes)",
}


def validate_gentle_config(config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Save-time check, naming the field (``provider.validate_config``)."""
    cfg = config or {}
    pause_raw = str(cfg.get("pagePauseSeconds") if cfg.get("pagePauseSeconds") is not None else "").strip()
    if pause_raw:
        try:
            pause = float(pause_raw)
        except ValueError:
            return PAGE_PAUSE_INVALID_MESSAGE
        if not (math.isfinite(pause) and PAGE_PAUSE_FIELD_MIN <= pause <= PAGE_PAUSE_FIELD_MAX):
            return PAGE_PAUSE_INVALID_MESSAGE
    one = str(cfg.get("oneRequestAtATime") if cfg.get("oneRequestAtATime") is not None else "").strip().lower()
    if one and one not in (ONE_AT_A_TIME_YES, ONE_AT_A_TIME_NO):
        return "One request at a time per server must be Yes or No."
    slow_raw = str(cfg.get("slowPageSeconds") if cfg.get("slowPageSeconds") is not None else "").strip()
    if slow_raw:
        try:
            slow = float(slow_raw)
        except ValueError:
            slow = -1.0
        if not (math.isfinite(slow) and SLOW_PAGE_FIELD_MIN <= slow <= SLOW_PAGE_FIELD_MAX):
            return "Slow page must be a number from 0 to 300 seconds (0 = off)."
    for key, low, high in (
        ("lookupCacheMinutes", LOOKUP_CACHE_FIELD_MIN, LOOKUP_CACHE_FIELD_MAX),
        ("stockPageSize", STOCK_PAGE_SIZE_FIELD_MIN, STOCK_PAGE_SIZE_FIELD_MAX),
        ("stopAfterFailures", STOP_AFTER_FIELD_MIN, STOP_AFTER_FIELD_MAX),
        ("stopMinutes", STOP_MINUTES_FIELD_MIN, STOP_MINUTES_FIELD_MAX),
    ):
        raw = str(cfg.get(key) if cfg.get(key) is not None else "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            return f"{_FIELD_LABELS.get(key, key)} must be a whole number."
        if not (low <= value <= high):
            return f"{_FIELD_LABELS.get(key, key)} must be between {low} and {high}."
    return None


_sleep = time.sleep


def sleep_between_pages(
    seconds: float, *, should_stop: Optional[Callable[[], bool]] = None
) -> bool:
    """The ONE place a walk pauses between pages (tests stub this name).

    Sleeps in ``PAUSE_SLICE_SECONDS`` slices; after each slice ``should_stop``
    (when given) runs - it beats the job's heartbeat (a 10-minute pause must
    never read as a dead worker to the 15-minute orphan sweep) and returns
    ``True`` once the run was stopped. Returns ``False`` when the pause was cut
    short by a stop, ``True`` when it ran to the end."""
    remaining = float(seconds)
    while remaining > 0:
        step = min(PAUSE_SLICE_SECONDS, remaining)
        _sleep(step)
        remaining -= step
        if should_stop is not None and should_stop():
            return False
    return True


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
