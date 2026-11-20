"""Per-feed read window (DOC-FEED-WINDOW).

Which vendor door the poll reads (``pollBasis``: LastModified or DocDate), how
many days back each poll tick reaches (``pollLookbackDays``), and how many
DocDate days the scheduled re-check (the folded deletion sweep) re-reads
(``recheckDays``).

``ac_doc_feed.window_config`` NULL = :data:`DEFAULT_DOC_FEED_WINDOW`, which is
byte-for-byte the pre-window hard-coded behaviour (LastModified, yesterday ..
today, 45-day sweep), so an unedited feed behaves exactly as before.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .constants import SWEEP_WINDOW_DAYS

POLL_BASIS_LAST_MODIFIED = "last_modified"
POLL_BASIS_DOC_DATE = "doc_date"
POLL_BASES = (POLL_BASIS_LAST_MODIFIED, POLL_BASIS_DOC_DATE)

MIN_POLL_LOOKBACK_DAYS = 0
MAX_POLL_LOOKBACK_DAYS = 30
MIN_RECHECK_DAYS = 1
# Q5 - one vendor GET per day per re-check run; a longer reach is a backfill.
MAX_RECHECK_DAYS = 180

WINDOW_KEYS = ("pollBasis", "pollLookbackDays", "recheckDays")

DEFAULT_DOC_FEED_WINDOW: Dict[str, Any] = {
    "pollBasis": POLL_BASIS_LAST_MODIFIED,
    "pollLookbackDays": 1,
    "recheckDays": SWEEP_WINDOW_DAYS,
}


def resolve_window(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The feed's effective window: each stored key, else its default."""
    out = dict(DEFAULT_DOC_FEED_WINDOW)
    for key in WINDOW_KEYS:
        value = (stored or {}).get(key)
        if value is not None:
            out[key] = value
    return out


def _clean_int(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def validate_doc_feed_window(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Cleaned ``{pollBasis, pollLookbackDays, recheckDays}`` plus a
    per-field error map (the house 422 shape). Every key is required: the
    dialog always sends the whole window."""
    errors: Dict[str, str] = {}
    basis = str(raw.get("pollBasis") or "").strip()
    if basis not in POLL_BASES:
        errors["pollBasis"] = "Choose LastModified or DocDate."
        basis = POLL_BASIS_LAST_MODIFIED

    lookback = _clean_int(raw.get("pollLookbackDays"))
    if lookback is None or not (MIN_POLL_LOOKBACK_DAYS <= lookback <= MAX_POLL_LOOKBACK_DAYS):
        errors["pollLookbackDays"] = (
            f"Between {MIN_POLL_LOOKBACK_DAYS} and {MAX_POLL_LOOKBACK_DAYS} days."
        )
        lookback = DEFAULT_DOC_FEED_WINDOW["pollLookbackDays"]

    recheck = _clean_int(raw.get("recheckDays"))
    if recheck is None or not (MIN_RECHECK_DAYS <= recheck <= MAX_RECHECK_DAYS):
        errors["recheckDays"] = f"Between {MIN_RECHECK_DAYS} and {MAX_RECHECK_DAYS} days."
        recheck = DEFAULT_DOC_FEED_WINDOW["recheckDays"]

    return {"pollBasis": basis, "pollLookbackDays": lookback, "recheckDays": recheck}, errors
