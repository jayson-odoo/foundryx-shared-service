"""Per-feed schedule (sprint-5/19, AC-19-01..09).

A document feed's cadence uses the SAME shape, rules and maths as an ETL
task's schedule on the Entities tab: the poll is the "incremental" (every N
minutes, floor 1 minute - Entities' with-watermark floor, owner ruling Q1 on
PR #110; the poll reads the vendor's ``<doc>byLastModified`` endpoint, a
LastModified watermark), the deletion sweep is the "reconcile" (every N hours
>= 1, or daily at ``HH:MM`` UTC). Validation is ``etl_service.
validate_schedule`` and next-run maths is ``EtlService.next_run_times`` -
reused, never re-implemented.

``ac_doc_feed.schedule_config`` NULL = :data:`DEFAULT_DOC_FEED_SCHEDULE`,
which is byte-for-byte the pre-19 hard-coded cadence (poll 60 min, sweep
every 24 h), so an unedited feed behaves exactly as before.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from ..services.etl_service import (
    RECONCILE_MODE_INTERVAL,
    EtlService,
    validate_schedule,
)

SCHEDULE_KEYS = ("incrementalMinutes", "reconcileMode", "reconcileHours", "reconcileAt")

# `next_run_times` picks its incremental floor from `watermarkColumn`; the
# poll is a LastModified read, so it runs on the with-watermark floor.
_POLL_WATERMARK = {"watermarkColumn": "LastModified"}

DEFAULT_DOC_FEED_SCHEDULE: Dict[str, Any] = {
    "incrementalMinutes": 60,
    "reconcileMode": RECONCILE_MODE_INTERVAL,
    "reconcileHours": 24,
    "reconcileAt": None,
}


def resolve_schedule(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The feed's effective schedule: the stored one, else the defaults."""
    if not stored:
        return dict(DEFAULT_DOC_FEED_SCHEDULE)
    return {key: stored.get(key) for key in SCHEDULE_KEYS}


def validate_doc_feed_schedule(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Entities' rule set with the with-watermark (1 minute) poll floor."""
    return validate_schedule(raw, has_watermark=True)


def next_poll_at(schedule: Dict[str, Any], now: datetime) -> datetime:
    return EtlService.next_run_times({**schedule, **_POLL_WATERMARK}, now=now)[0]


def next_sweep_at(schedule: Dict[str, Any], now: datetime) -> datetime:
    return EtlService.next_run_times({**schedule, **_POLL_WATERMARK}, now=now)[1]


def poll_changed(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    return old["incrementalMinutes"] != new["incrementalMinutes"]


def sweep_changed(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    return any(old[key] != new[key] for key in ("reconcileMode", "reconcileHours", "reconcileAt"))
