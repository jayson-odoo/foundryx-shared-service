"""Report bucket windows (plan 30, roadmap A9 - D-A9-8).

Bucket edges are computed HERE, in pure Python from `zoneinfo`, and applied by
`report_queries.py` as conditional aggregates in ONE SQL pass - never
`date_trunc`/`strftime`. That is what makes the pytest SQLite numbers and the
production Postgres numbers byte-identical, and what makes a DST-spanning day
bucket 23/25h wide by construction rather than a special case (AC-RPT-11/12).

No DB access in this module - every function is a pure function over dates/
datetimes, fully unit-testable without a session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BUCKETS = 120
MAX_RANGE_DAYS = 366

GRANULARITIES = ("hour", "day", "week", "month")


class InvalidTimezone(Exception):
    """`tz` is not a zoneinfo-resolvable IANA name."""


class InvalidDateFormat(Exception):
    """`from`/`to` is not `YYYY-MM-DD`."""


class InvalidRangeOrder(Exception):
    """`to` is earlier than `from`."""


class RangeTooWide(Exception):
    """The requested range exceeds `MAX_RANGE_DAYS`."""


class BucketLimitExceeded(Exception):
    """The resolved granularity would produce more than `MAX_BUCKETS` buckets."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(f"This range would need {count} buckets (max {MAX_BUCKETS}).")


@dataclass(frozen=True)
class Bucket:
    key: str
    starts_at: datetime  # aware UTC
    ends_at: datetime  # aware UTC


def resolve_zone(tz_name: str) -> ZoneInfo:
    """422-worthy failure surfaced as `InvalidTimezone` - the router/filters
    layer maps it to `fieldErrors.tz`."""
    if not tz_name:
        raise InvalidTimezone(tz_name)
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise InvalidTimezone(tz_name) from exc


def parse_local_date(value: str) -> date:
    try:
        year_s, month_s, day_s = value.split("-")
        if len(year_s) != 4 or len(month_s) != 2 or len(day_s) != 2:
            raise ValueError("bad shape")
        return date(int(year_s), int(month_s), int(day_s))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidDateFormat(value) from exc


def resolve_range(from_date: date, to_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The half-open UTC window `[local_midnight(from), local_midnight(to + 1
    day))` - DST transitions inside the range are handled by the zone, never
    by a fixed offset (plan §"Definitions" / D-A9-8)."""
    if to_date < from_date:
        raise InvalidRangeOrder()
    if (to_date - from_date).days + 1 > MAX_RANGE_DAYS:
        raise RangeTooWide()
    start_local = datetime.combine(from_date, time.min, tzinfo=tz)
    end_local = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def auto_granularity(from_date: date, to_date: date) -> str:
    """AC-RPT-08: `<= 2 days` -> hour, `<= 62 days` -> day, `<= 366 days` ->
    week, else month (the last branch is presently unreachable given
    `MAX_RANGE_DAYS`, kept for when that cap changes)."""
    days = (to_date - from_date).days + 1
    if days <= 2:
        return "hour"
    if days <= 62:
        return "day"
    if days <= 366:
        return "week"
    return "month"


def _local_midnight(d: date, tz: ZoneInfo) -> datetime:
    """Freshly derived from calendar fields every call - never additive
    arithmetic across a boundary, so a DST transition on `d` is reflected
    exactly (AC-RPT-12)."""
    return datetime.combine(d, time.min, tzinfo=tz)


def _local_days(start_utc: datetime, end_utc: datetime, tz: ZoneInfo) -> List[date]:
    """Every local calendar day whose local midnight lies in
    `[start_utc, end_utc)` - `start_utc`/`end_utc` are themselves exact local
    midnights by construction (`resolve_range`), so this is a clean day walk."""
    cursor = start_utc.astimezone(tz).date()
    end_date = end_utc.astimezone(tz).date()
    days: List[date] = []
    while cursor < end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _hour_buckets(start_utc: datetime, end_utc: datetime, tz: ZoneInfo) -> List[Bucket]:
    buckets: List[Bucket] = []
    for d in _local_days(start_utc, end_utc, tz):
        day_start = _local_midnight(d, tz)
        for h in range(24):
            local_start = day_start + timedelta(hours=h)
            local_end = local_start + timedelta(hours=1)
            starts_at = local_start.astimezone(timezone.utc)
            ends_at = local_end.astimezone(timezone.utc)
            if ends_at <= start_utc or starts_at >= end_utc:
                continue
            buckets.append(Bucket(f"{d.isoformat()}T{h:02d}", starts_at, ends_at))
            if len(buckets) > MAX_BUCKETS:
                raise BucketLimitExceeded(len(buckets))
    return buckets


def _day_buckets(days: List[date], tz: ZoneInfo) -> List[Bucket]:
    buckets: List[Bucket] = []
    for d in days:
        starts_at = _local_midnight(d, tz).astimezone(timezone.utc)
        ends_at = _local_midnight(d + timedelta(days=1), tz).astimezone(timezone.utc)
        buckets.append(Bucket(d.isoformat(), starts_at, ends_at))
        if len(buckets) > MAX_BUCKETS:
            raise BucketLimitExceeded(len(buckets))
    return buckets


def _iso_week_key(d: date) -> str:
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _grouped_buckets(days: List[date], tz: ZoneInfo, key_fn) -> List[Bucket]:
    """Group the day list by `key_fn` (ISO week or Y-M); a group's edges are
    its first day's local midnight through the day AFTER its last day's local
    midnight - both freshly derived, so DST at either edge is exact."""
    order: List[str] = []
    groups: dict[str, list[date]] = {}
    for d in days:
        k = key_fn(d)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(d)
    buckets: List[Bucket] = []
    for k in order:
        group_days = groups[k]
        first, last = group_days[0], group_days[-1]
        starts_at = _local_midnight(first, tz).astimezone(timezone.utc)
        ends_at = _local_midnight(last + timedelta(days=1), tz).astimezone(timezone.utc)
        buckets.append(Bucket(k, starts_at, ends_at))
        if len(buckets) > MAX_BUCKETS:
            raise BucketLimitExceeded(len(buckets))
    return buckets


def bucket_edges(start_utc: datetime, end_utc: datetime, tz: ZoneInfo, granularity: str) -> List[Bucket]:
    """The list of `Bucket`s covering `[start_utc, end_utc)`, keyed LOCAL
    (D-A9-11 - the client formats the axis label from `key` and never
    re-applies a timezone). Raises `BucketLimitExceeded` above `MAX_BUCKETS`."""
    if granularity == "hour":
        return _hour_buckets(start_utc, end_utc, tz)
    days = _local_days(start_utc, end_utc, tz)
    if granularity == "day":
        return _day_buckets(days, tz)
    if granularity == "week":
        return _grouped_buckets(days, tz, _iso_week_key)
    if granularity == "month":
        return _grouped_buckets(days, tz, _month_key)
    raise ValueError(f"unknown granularity: {granularity}")
