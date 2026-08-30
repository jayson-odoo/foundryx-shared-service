"""Canonical row hashing (plan 22 §2.2, AC-22-16).

    !!  THE HASH IS THE ONLY THING WE STORE ABOUT A SOURCE ROW.  !!

``ac_row_hash`` holds hashes, never row copies, so this normalisation IS the
change-detection contract - and it has a failure mode on BOTH sides:

* **Too strict** - one dialect decoding ``1`` as ``int`` and another as
  ``Decimal('1')`` would restage every row on every run, forever. That is not
  a cosmetic bug: it turns reconcile into a full re-push and hammers the
  consumer. So every numeric decoding of one value normalises to ONE token.
* **Too loose** - ``None`` colliding with ``''``, or ``True`` with ``1``,
  swallows a real change silently, which nobody ever notices. So each type
  family carries its own prefix and can never collide with another's.

Design notes worth keeping:

* Values are TYPE-TAGGED (``s:``/``n:``/``b:``/``t:``…). Tagging is what lets
  numerics be normalised aggressively without ``1`` ever meeting ``"1"``.
* Datetimes normalise to an aware-UTC instant; a NAIVE datetime is read as UTC
  (the house convention - every column we own is ``UTCDateTime``, and a source
  driver that drops the offset must not read as a different instant).
* Column NAMES are hashed alongside their values, so swapping two columns'
  contents is a change.
* sha256 hex, never Python ``hash()`` - that is salted per process, so every
  restart would restage the whole table.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, List, Mapping, Sequence

__all__ = ["compared_columns_for", "normalize_value", "row_hash"]

# Record separator between a name and its value, and between pairs. Chosen from
# the ASCII control block so it can never appear in a column name.
_UNIT = "\x1f"
_RECORD = "\x1e"


def _numeric_token(value: Any) -> str:
    """One canonical token for any numeric decoding of the same value.

    ``Decimal.normalize`` collapses trailing zeros (``1.50`` → ``1.5``,
    ``1.000`` → ``1``); floats go through ``str`` first so ``1.5`` does not
    become ``1.5000000000000000444089209850062616169452667236328125``.
    ``normalize`` renders large integers in exponent form (``1E+3``), so the
    result is expanded back through ``quantize``-free plain-string formatting.
    """
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "s:" + str(value)
    if number.is_nan() or number.is_infinite():
        return "n:" + str(number)
    normalized = number.normalize()
    text = format(normalized, "f")
    # ``Decimal('-0')`` normalises to ``-0``; one zero, one token.
    if text in ("-0", "-0.0"):
        text = "0"
    return "n:" + text


def normalize_value(value: Any) -> str:
    """A source cell as a type-tagged, dialect-stable token."""
    if value is None:
        return "\x00null"
    # bool BEFORE int - ``isinstance(True, int)`` is True, and a boolean must
    # never collide with 1/0 (MySQL returns tinyint, Postgres a real bool).
    if isinstance(value, bool):
        return "b:1" if value else "b:0"
    if isinstance(value, (int, float, Decimal)):
        return _numeric_token(value)
    if isinstance(value, datetime):
        stamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return "t:" + stamp.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return "d:" + value.isoformat()
    if isinstance(value, dt_time):
        return "T:" + value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "x:" + bytes(value).hex()
    if isinstance(value, str):
        return "s:" + value
    if isinstance(value, (list, tuple)):
        return "a:[" + ",".join(normalize_value(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return (
            "m:{"
            + ",".join(
                f"{k}={normalize_value(value[k])}" for k in sorted(value, key=str)
            )
            + "}"
        )
    return "s:" + str(value)


def row_hash(row: Mapping[str, Any], compared_columns: Sequence[str]) -> str:
    """sha256 over the compared columns of ONE source row, name-sorted.

    Sorting means a config edit that merely REORDERS the compared set does not
    invalidate every stored hash; a column absent from ``row`` hashes exactly
    like an explicit NULL (a query that stopped selecting it is an absence, not
    a change).
    """
    parts: List[str] = []
    for name in sorted(compared_columns):
        parts.append(str(name))
        parts.append(normalize_value(row.get(name)))
    return hashlib.sha256(_RECORD.join(parts).encode("utf-8")).hexdigest()


def compared_columns_for(
    *,
    configured: Sequence[str],
    result_columns: Sequence[str],
    key_columns: Sequence[str],
) -> List[str]:
    """The effective compared set (AC-22-11/16).

    Empty configuration = every result column MINUS the keys (a key change is a
    new record, never an update). A configured pick the query no longer returns
    is dropped: hashing a column that does not exist would hash NULL for every
    row and blind the diff for the columns that DO exist.
    """
    keys = {str(k) for k in key_columns}
    available = [str(c) for c in result_columns]
    if configured:
        picked = {str(c) for c in configured}
        return sorted(c for c in available if c in picked and c not in keys)
    return sorted(c for c in available if c not in keys)


# ``_UNIT`` is kept as the documented separator for future composite keys; the
# row hash uses ``_RECORD`` between every element (name and value alike) so a
# name containing the value separator could never forge a different row.
assert _UNIT != _RECORD
