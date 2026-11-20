"""MYT clock (D6) - a FIXED UTC+8 offset, no DST, no tzdata dependency.

Malaysia observes no daylight saving, so a plain fixed-offset ``timezone`` is
exact year-round - unlike ``zoneinfo``, it needs no OS tz database on a slim
image.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8), "MYT")


def myt_date(aware_utc: datetime) -> date:
    """The MYT calendar date of an aware-UTC (or any aware) timestamp."""
    return aware_utc.astimezone(MYT).date()


def myt_today() -> date:
    """Today's MYT calendar date (the one place the AutoCount day-list lookups read the clock)."""
    return myt_date(datetime.now(timezone.utc))


def yyyymmdd(day: date) -> str:
    """``yyyyMMdd`` with no separators - the vendor's own query-string form."""
    return day.strftime("%Y%m%d")
