"""AUTOCOUNT-LOAD-STRATEGY - office hours come from Sorento CRM (owner 27 Nov:
"office hours is based on the settings in sorento crm, we have set there ady").

The CRM serves them on ``GET /api/v1/external/work-calendar``::

    {"timezone": "Asia/Kuala_Lumpur",
     "working_hours_start": "09:00 A.M.", "working_hours_end": "05:30 P.M.",
     "working_day_ranges": [{"start_weekday": "Monday", "end_weekday": "Friday"}]}

and today's holiday answer on ``.../is-working-day`` (``{"is_working_day": bool}``).
SS reads both per Sorento connection with that connection's own API key and
keeps them for ``CACHE_SECONDS``. Any failure (no access, bad shape) means
"every hour is office hours" - today's behaviour, nothing slows down - and the
reason is shown on the Sorento connection page.

How the scheduler uses it (``scheduler._sweep_one``), open-REST tasks only:
outside office hours the stock balance runs at most every
``OFF_HOURS_STOCK_MINUTES``; every other open-REST list (products, customers,
masters) waits for the next office-hours start. The nightly full run is
never held back.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CACHE_SECONDS = 3600
OFF_HOURS_STOCK_MINUTES = 60
DEFAULT_TIMEZONE = "Asia/Kuala_Lumpur"
CALENDAR_TIMEOUT_SECONDS = 10.0

_WEEKDAYS = {
    name: i for i, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    )
}
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp])?\.?\s*[Mm]?\.?\s*$")


@dataclass(frozen=True)
class OfficeHours:
    zone: ZoneInfo
    days: FrozenSet[int]
    start_minute: int
    end_minute: int
    # Today's date (in ``zone``) when the CRM says it is not a working day.
    holiday: Optional[date] = None

    def is_open(self, at: datetime) -> bool:
        local = at.astimezone(self.zone)
        if self.holiday is not None and local.date() == self.holiday:
            return False
        if local.weekday() not in self.days:
            return False
        minute = local.hour * 60 + local.minute
        return self.start_minute <= minute < self.end_minute

    def next_open(self, at: datetime) -> datetime:
        """The next office-hours start strictly after ``at`` (UTC)."""
        local = at.astimezone(self.zone)
        for offset in range(0, 8):
            day = (local + timedelta(days=offset)).date()
            if day.weekday() not in self.days:
                continue
            if self.holiday is not None and day == self.holiday:
                continue
            start = datetime(
                day.year, day.month, day.day, self.start_minute // 60, self.start_minute % 60,
                tzinfo=self.zone,
            )
            if start > local:
                return start.astimezone(timezone.utc)
        return (at + timedelta(days=1)).astimezone(timezone.utc)

    def describe(self) -> str:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        ordered = sorted(self.days)
        groups = []
        run = [ordered[0]] if ordered else []
        for d in ordered[1:]:
            if d == run[-1] + 1:
                run.append(d)
            else:
                groups.append(run)
                run = [d]
        if run:
            groups.append(run)
        days = ", ".join(
            names[g[0]] if len(g) == 1 else f"{names[g[0]]} - {names[g[-1]]}" for g in groups
        )
        return f"{days}, {_clock(self.start_minute)} - {_clock(self.end_minute)}"


def _clock(minute: int) -> str:
    hour, mins = divmod(minute, 60)
    return f"{hour % 12 or 12}:{mins:02d} {'am' if hour < 12 else 'pm'}"


def _parse_time(raw: Any) -> int:
    match = _TIME_RE.match(str(raw or ""))
    if not match:
        raise ValueError(f"the office hours time '{raw}' could not be read")
    hour, minute, half = int(match.group(1)), int(match.group(2)), match.group(3)
    if minute > 59:
        raise ValueError(f"the office hours time '{raw}' could not be read")
    if half:
        if not 1 <= hour <= 12:
            raise ValueError(f"the office hours time '{raw}' could not be read")
        hour = hour % 12 + (12 if half.lower() == "p" else 0)
    elif hour > 23:
        raise ValueError(f"the office hours time '{raw}' could not be read")
    return hour * 60 + minute


def parse_work_calendar(
    calendar: Dict[str, Any], working_day: Optional[Dict[str, Any]] = None, *, now: datetime,
) -> OfficeHours:
    """Raises ``ValueError`` with a plain reason when the shape is off."""
    zone_name = str(calendar.get("timezone") or DEFAULT_TIMEZONE)
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"the time zone '{zone_name}' is not known") from exc
    start = _parse_time(calendar.get("working_hours_start"))
    end = _parse_time(calendar.get("working_hours_end"))
    if end <= start:
        raise ValueError("office hours end before they start")
    ranges = calendar.get("working_day_ranges")
    if not isinstance(ranges, list) or not ranges:
        raise ValueError("no working days were given")
    days = set()
    for item in ranges:
        if not isinstance(item, dict):
            raise ValueError("a working day range could not be read")
        first = _WEEKDAYS.get(str(item.get("start_weekday") or "").strip().lower())
        last = _WEEKDAYS.get(str(item.get("end_weekday") or "").strip().lower())
        if first is None or last is None:
            raise ValueError("a working day range names an unknown weekday")
        day = first
        while True:
            days.add(day)
            if day == last:
                break
            day = (day + 1) % 7
    holiday = None
    if isinstance(working_day, dict) and working_day.get("is_working_day") is False:
        holiday = now.astimezone(zone).date()
    return OfficeHours(zone=zone, days=frozenset(days), start_minute=start, end_minute=end, holiday=holiday)


@dataclass(frozen=True)
class CalendarRead:
    hours: Optional[OfficeHours]
    error: Optional[str]


# ── per Sorento connection, cached ─────────────────────────────────────────

_lock = threading.Lock()
_cache: Dict[Tuple[str, ...], Tuple[float, CalendarRead]] = {}
_monotonic = time.monotonic


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def read_for_connection(conn: Any, credentials: Dict[str, Any], *, now: datetime,
                        transport: Any = None) -> CalendarRead:
    """The office hours of one Sorento connection (cached ``CACHE_SECONDS``;
    the holiday answer is refreshed when the cached day is not today)."""
    # The base URL and the key are part of the cache key: a saved change on
    # the connection reads the calendar again at once.
    import hashlib

    secret = hashlib.sha256(str((credentials or {}).get("apiKey") or "").encode()).hexdigest()[:16]
    key = (str(conn.tenant_id), str(conn.id), str((conn.config_json or {}).get("baseUrl") or ""), secret)
    stamp = _monotonic()
    with _lock:
        hit = _cache.get(key)
    if hit is not None and stamp - hit[0] < CACHE_SECONDS:
        hours = hit[1].hours
        if hours is None or hours.holiday is None or hours.holiday == now.astimezone(hours.zone).date():
            return hit[1]
    read = _fetch(conn, credentials, now=now, transport=transport)
    with _lock:
        _cache[key] = (stamp, read)
    return read


def _fetch(conn: Any, credentials: Dict[str, Any], *, now: datetime, transport: Any) -> CalendarRead:
    from .sinks_sorento import SorentoWorkCalendarError, sorento_sink_from_connection

    try:
        sink = sorento_sink_from_connection(
            conn.config_json or {}, credentials or {}, entity_type="product",
            transport=transport, timeout=CALENDAR_TIMEOUT_SECONDS,
        )
        calendar, working_day = sink.fetch_work_calendar()
        return CalendarRead(hours=parse_work_calendar(calendar or {}, working_day, now=now), error=None)
    except SorentoWorkCalendarError as exc:
        return CalendarRead(hours=None, error=str(exc))
    except ValueError as exc:
        return CalendarRead(hours=None, error=str(exc))
    except Exception:  # noqa: BLE001 - never block a sync on the calendar
        return CalendarRead(hours=None, error="the work calendar could not be read")


def read_for_company(db: Any, tenant_id: str, company: Any, *, now: datetime) -> CalendarRead:
    """The office hours of the Sorento connection a company delivers to.
    No Sorento connection = no office hours (every hour counts)."""
    from .repositories import ConnectionRepository
    from .sorento_provider import SORENTO_PROVIDER_KEY

    connection_id = getattr(company, "sink_connection_id", None)
    if not connection_id:
        return CalendarRead(hours=None, error=None)
    conn = ConnectionRepository(db).get_for_provider(tenant_id, connection_id, SORENTO_PROVIDER_KEY)
    if conn is None:
        return CalendarRead(hours=None, error=None)
    try:
        from app.secrets import decrypt_secret

        credentials = decrypt_secret(conn.credentials_json) if conn.credentials_json else {}
    except Exception:  # noqa: BLE001 - InvalidToken et al.: plain, never a 500
        return CalendarRead(hours=None, error="the Sorento API key could not be read")
    return read_for_connection(conn, credentials or {}, now=now)


def hint_text(read: CalendarRead) -> Optional[str]:
    """The line under the Sorento connection's base URL."""
    if read.hours is not None:
        return f"Office hours from Sorento CRM: {read.hours.describe()}"
    if read.error:
        return (
            f"Office hours could not be read from Sorento CRM ({read.error}); "
            "every hour counts as office hours."
        )
    return None
