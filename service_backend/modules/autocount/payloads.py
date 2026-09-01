"""Bounding stored log payloads (plan §11, AC-13-46).

A single AutoCount read legitimately returns 161 documents, each with a nested
line array. Storing that verbatim on every activity row would put megabytes per
row into ``integration_activity`` - a table that already has a per-second volume
guard because it is written on hot paths.

So payloads are BOUNDED. The rule that matters is the one AC-13-46 exists for:

    !!  A TRUNCATED LOG MUST NEVER READ AS A COMPLETE ONE.  !!

Silently dropping the tail of a ``ResultTable`` is the same class of failure as
silently truncating a fetch - a diagnostician reads "3 documents came back",
concludes the vendor sent 3, and chases the wrong bug. Every reduction here is
therefore MARKED, in place:

* a shortened list becomes ``{"__truncated__": true, "keptItems": n,
  "totalItems": N, "items": [...]}`` - the shape CHANGES, so it cannot be
  mistaken for a complete array;
* an over-long string keeps a visible ``…[truncated]`` suffix;
* an over-large payload collapses to a marker carrying its original byte count
  and a preview;
* and the caller stamps ``__truncated__`` on the top-level record, so presence
  of that key alone answers "is this the whole story?".

Masking happens BEFORE bounding (``client.py``), so a preview string can never
contain a credential that the mask would have caught.
"""
from __future__ import annotations

import json
from typing import Any, Tuple

__all__ = [
    "TRUNCATED_KEY",
    "MAX_LIST_ITEMS",
    "MAX_PAYLOAD_BYTES",
    "MAX_STRING_CHARS",
    "bound_payload",
    "mark_truncated",
]

# The marker key. Its PRESENCE means "this record is not the whole story".
TRUNCATED_KEY = "__truncated__"

# A vendor ResultTable of 161 documents is normal; five is enough to see the
# shape of a mapping problem, and the count of what was dropped is recorded.
MAX_LIST_ITEMS = 5
# Hard ceiling on the serialised row. Generous enough for five documents with
# their lines, small enough that a burst cannot bloat the table.
MAX_PAYLOAD_BYTES = 8_000
# A .NET StackTraceString runs to thousands of characters on its own.
MAX_STRING_CHARS = 1_000
# Structural depth cap (mirrors ``mask_payload``'s) - a pathological payload
# must not recurse forever.
_MAX_DEPTH = 12


def _bound(value: Any, max_items: int, depth: int = 0) -> Tuple[Any, bool]:
    """Recursively bound one value. Returns ``(bounded, was_truncated)``."""
    if depth > _MAX_DEPTH:
        return {TRUNCATED_KEY: True, "reason": "maximum nesting depth"}, True

    if isinstance(value, dict):
        out = {}
        truncated = False
        for key, item in value.items():
            out[str(key)], hit = _bound(item, max_items, depth + 1)
            truncated = truncated or hit
        return out, truncated

    if isinstance(value, list):
        kept = []
        truncated = False
        for item in value[:max_items]:
            bounded, hit = _bound(item, max_items, depth + 1)
            kept.append(bounded)
            truncated = truncated or hit
        if len(value) > max_items:
            # The SHAPE changes deliberately: a reader cannot mistake this for a
            # complete array, and the real total is right there.
            return (
                {
                    TRUNCATED_KEY: True,
                    "keptItems": len(kept),
                    "totalItems": len(value),
                    "items": kept,
                },
                True,
            )
        return kept, truncated

    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        return f"{value[:MAX_STRING_CHARS]}…[truncated]", True

    # A scalar within the length cap is complete as-is.
    return value, False


def bound_payload(
    value: Any,
    *,
    max_items: int = MAX_LIST_ITEMS,
    max_bytes: int = MAX_PAYLOAD_BYTES,
) -> Tuple[Any, bool]:
    """Bound a masked JSON-ish payload for storage.

    Returns ``(bounded_value, was_truncated)``. The caller stamps
    ``TRUNCATED_KEY`` on the top-level record when the flag is set, so the
    stored row states plainly that it is partial.
    """
    if value is None:
        return None, False

    bounded, truncated = _bound(value, max_items)

    try:
        encoded = json.dumps(bounded, default=str)
    except (TypeError, ValueError):
        # Unserialisable is a truncation too - say so rather than storing NULL
        # and letting the row read as "no payload".
        return (
            {
                TRUNCATED_KEY: True,
                "reason": "payload was not JSON-serialisable",
                "preview": str(value)[:MAX_STRING_CHARS],
            },
            True,
        )

    if len(encoded) > max_bytes:
        return (
            {
                TRUNCATED_KEY: True,
                "reason": f"payload exceeded {max_bytes} bytes",
                "originalBytes": len(encoded),
                "preview": encoded[:MAX_STRING_CHARS],
            },
            True,
        )

    return bounded, truncated


def mark_truncated(record: dict, truncated: bool) -> dict:
    """Stamp the top-level truncation flag when (and only when) something was
    dropped. Absence of the key is the positive statement "this is complete"."""
    if truncated:
        record[TRUNCATED_KEY] = True
    return record
