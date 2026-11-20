"""Percentile / median / average reduction (plan 30, D-A9-9).

Pure Python, over an already-bounded list of ints - `percentile_cont` is
Postgres-only and timestamp arithmetic is dialect-specific, so this is the ONE
place numbers are reduced, giving pytest's SQLite run and production Postgres
byte-identical results. No DB access in this module.
"""
from __future__ import annotations

import math
from typing import List, Optional, TypedDict

# The respond.io parity response-time distribution (plan §"Definitions"),
# half-open `[lo, hi)` in seconds - `hi=None` means unbounded.
RESPONSE_BUCKETS: List[tuple[str, str, int, Optional[int]]] = [
    ("lt30s", "< 30s", 0, 30),
    ("30s-2m", "30s - 2m", 30, 120),
    ("2m-5m", "2m - 5m", 120, 300),
    ("5m-10m", "5m - 10m", 300, 600),
    ("10m-30m", "10m - 30m", 600, 1800),
    ("30m-1h", "30m - 1h", 1800, 3600),
    ("gt1h", "> 1h", 3600, None),
]


def _round_half_up(value: float) -> int:
    """Whole-second rounding, half-up (the plan's percentile definition) -
    all inputs here are non-negative durations."""
    return math.floor(value + 0.5)


def percentile(sorted_values: List[float], p: float) -> Optional[int]:
    """Linear interpolation on the ALREADY-SORTED sample:
    `i = p * (n - 1)`, `value = s[floor(i)] + (s[ceil(i)] - s[floor(i)]) * (i - floor(i))`,
    rounded half-up to whole seconds; `n = 0` yields `None`."""
    n = len(sorted_values)
    if n == 0:
        return None
    i = p * (n - 1)
    lo = math.floor(i)
    hi = math.ceil(i)
    value = sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (i - lo)
    return _round_half_up(value)


def median(sorted_values: List[float]) -> Optional[int]:
    return percentile(sorted_values, 0.5)


def average(values: List[float]) -> Optional[int]:
    if not values:
        return None
    return _round_half_up(sum(values) / len(values))


class DurationStatsDict(TypedDict):
    medianSeconds: Optional[int]
    p90Seconds: Optional[int]
    averageSeconds: Optional[int]
    sampleCount: int


def stats_of(values: List[float]) -> DurationStatsDict:
    """The `{medianSeconds, p90Seconds, averageSeconds, sampleCount}` shape
    every duration surface (dashboard totals, responses/resolutions reports,
    per-user breakdowns) reduces to. `derivedFromMessages` is layered on by
    the caller (only the response-time path has it)."""
    sorted_values = sorted(values)
    return {
        "medianSeconds": median(sorted_values),
        "p90Seconds": percentile(sorted_values, 0.9),
        "averageSeconds": average(values),
        "sampleCount": len(values),
    }


def bucket_distribution(values: List[float]) -> List[dict]:
    """The seven-bucket response-time distribution (`reports/responses`,
    S2) - `percent` is over `len(values)`, one decimal."""
    counts = {key: 0 for key, _, _, _ in RESPONSE_BUCKETS}
    for v in values:
        for key, _label, lo, hi in RESPONSE_BUCKETS:
            if v >= lo and (hi is None or v < hi):
                counts[key] += 1
                break
    total = len(values)
    rows = []
    for key, label, _lo, _hi in RESPONSE_BUCKETS:
        count = counts[key]
        percent = round(count / total * 100, 1) if total else 0.0
        rows.append({"bucket": key, "label": label, "count": count, "percent": percent})
    return rows
