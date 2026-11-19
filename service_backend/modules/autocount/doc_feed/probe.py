"""SLOW-MOVING-BACKFILL S0.1 - find a book's earliest DocDate through the
vendor ``bydocdate`` doors (read-only).

There is no vendor door for MIN(DocDate), so the probe walks days: a coarse
pass reads one day every ``stride`` days from ``from_day``; at the first
non-empty day it steps back over the previous stride window day by day and
returns the first day that holds a document. A book whose first documents sit
only on days the coarse pass skipped inside a stride is found one stride
later at worst (documents land on most business days, so a 7-day stride
practically never skips a week). The exact answer is ``SELECT MIN(DocDate)``
on the book's DO / GRN tables where an SQL door reaches the book.

Pure over a ``read_day(day) -> list`` callable so it is tested without a
vendor; ``scripts/autocount_doc_date_probe.py`` wires it to a feed.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, List, Optional


def earliest_doc_day(
    read_day: Callable[[date], List[Any]],
    *,
    from_day: date,
    to_day: date,
    stride: int = 7,
) -> Optional[date]:
    """The first day in ``from_day..to_day`` with a document, or ``None``."""
    if stride < 1:
        raise ValueError("stride must be at least 1")
    previous = from_day - timedelta(days=1)
    day = from_day
    while day <= to_day:
        if read_day(day):
            probe = max(previous + timedelta(days=1), from_day)
            while probe < day:
                if read_day(probe):
                    return probe
                probe += timedelta(days=1)
            return day
        previous = day
        day += timedelta(days=stride)
    # the tail after the last coarse day
    probe = previous + timedelta(days=1)
    while probe <= to_day:
        if read_day(probe):
            return probe
        probe += timedelta(days=1)
    return None


def floor_for(earliest: Optional[date], *, default_floor: date) -> date:
    """The backfill floor: 01/01 of the earliest document's year when that is
    before ``default_floor``, else ``default_floor``."""
    if earliest is None or earliest >= default_floor:
        return default_floor
    return date(earliest.year, 1, 1)
