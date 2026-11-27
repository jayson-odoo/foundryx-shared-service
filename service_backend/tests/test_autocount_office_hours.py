"""AUTOCOUNT-LOAD-STRATEGY LS-7 - office hours come from Sorento CRM's work
calendar (owner 27 Nov). Outside them the stock balance runs at most hourly
and the other open-REST lists wait for office hours; the nightly full run is
never held back. A calendar that cannot be read = every hour is office hours.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from modules.autocount import office_hours
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_STOCK_BALANCE
from modules.autocount.models import SOURCE_IMPL_AUTOCOUNT_HTTP, AcEntityConfig

MYT = timezone(timedelta(hours=8))
CALENDAR = {
    "timezone": "Asia/Kuala_Lumpur",
    "working_hours_start": "09:00 A.M.",
    "working_hours_end": "05:30 P.M.",
    "working_day_ranges": [{"start_weekday": "Monday", "end_weekday": "Friday"}],
}


def _myt(day: int, hour: int, minute: int = 0) -> datetime:
    # 2026-11-23 is a Monday.
    return datetime(2026, 11, day, hour, minute, tzinfo=MYT).astimezone(timezone.utc)


_REAL_FETCH = office_hours._fetch


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(office_hours, "_fetch", _REAL_FETCH)
    office_hours.clear_cache()
    yield
    office_hours.clear_cache()


# ── the calendar (pure) ─────────────────────────────────────────────────────


def test_reads_the_crm_shape():
    hours = office_hours.parse_work_calendar(CALENDAR, {"is_working_day": True}, now=_myt(23, 10))
    assert hours.is_open(_myt(23, 9, 0))
    assert hours.is_open(_myt(27, 17, 29))
    assert not hours.is_open(_myt(27, 17, 30))
    assert not hours.is_open(_myt(23, 8, 59))
    assert not hours.is_open(_myt(28, 10))  # Saturday
    assert hours.describe() == "Monday - Friday, 9:00 am - 5:30 pm"


def test_a_gap_day_splits_the_ranges():
    cal = {**CALENDAR, "working_day_ranges": [
        {"start_weekday": "Monday", "end_weekday": "Tuesday"},
        {"start_weekday": "Thursday", "end_weekday": "Saturday"},
    ]}
    hours = office_hours.parse_work_calendar(cal, None, now=_myt(23, 10))
    assert not hours.is_open(_myt(25, 10))  # Wednesday
    assert hours.is_open(_myt(28, 10))  # Saturday
    assert hours.describe() == "Monday - Tuesday, Thursday - Saturday, 9:00 am - 5:30 pm"


def test_a_public_holiday_today_is_outside_office_hours():
    hours = office_hours.parse_work_calendar(CALENDAR, {"is_working_day": False}, now=_myt(24, 8))
    assert not hours.is_open(_myt(24, 10))
    assert hours.is_open(_myt(25, 10))
    assert hours.next_open(_myt(24, 10)) == _myt(25, 9)


def test_next_open_skips_the_weekend():
    hours = office_hours.parse_work_calendar(CALENDAR, None, now=_myt(27, 18))
    assert hours.next_open(_myt(27, 18)) == _myt(30, 9)
    assert hours.next_open(_myt(23, 7)) == _myt(23, 9)


@pytest.mark.parametrize("bad", [
    {**CALENDAR, "working_hours_start": "nine"},
    {**CALENDAR, "working_hours_end": "08:00 A.M."},
    {**CALENDAR, "working_day_ranges": []},
    {**CALENDAR, "working_day_ranges": [{"start_weekday": "Funday", "end_weekday": "Friday"}]},
    {**CALENDAR, "timezone": "Mars/Base"},
])
def test_a_shape_it_cannot_read_is_a_plain_error(bad):
    with pytest.raises(ValueError):
        office_hours.parse_work_calendar(bad, None, now=_myt(23, 10))


# ── the CRM read ────────────────────────────────────────────────────────────


class _Conn:
    tenant_id = "t1"
    id = "crm-1"
    config_json = {"baseUrl": "https://crm.example.test"}


def _crm(status=200, calendar=CALENDAR, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        assert request.headers["X-API-Key"] == "k"
        if status != 200:
            return httpx.Response(status, json={})
        if request.url.path.endswith("/is-working-day"):
            return httpx.Response(200, json={"is_working_day": True})
        return httpx.Response(200, json=calendar)
    return httpx.MockTransport(handler)


def test_reads_both_doors_with_the_connection_key_and_caches_for_an_hour(monkeypatch):
    calls = []
    clock = {"t": 1000.0}
    monkeypatch.setattr(office_hours, "_monotonic", lambda: clock["t"])
    transport = _crm(calls=calls)
    read = office_hours.read_for_connection(_Conn(), {"apiKey": "k"}, now=_myt(23, 10), transport=transport)
    assert read.hours is not None and read.error is None
    assert [r.url.path for r in calls] == [
        "/api/v1/external/work-calendar", "/api/v1/external/work-calendar/is-working-day",
    ]
    office_hours.read_for_connection(_Conn(), {"apiKey": "k"}, now=_myt(23, 10), transport=transport)
    assert len(calls) == 2
    clock["t"] += 3601
    office_hours.read_for_connection(_Conn(), {"apiKey": "k"}, now=_myt(23, 11), transport=transport)
    assert len(calls) == 4


def test_a_key_without_access_reads_as_always_open_with_the_reason():
    read = office_hours.read_for_connection(_Conn(), {"apiKey": "k"}, now=_myt(23, 10), transport=_crm(403))
    assert read.hours is None
    assert office_hours.hint_text(read) == (
        "Office hours could not be read from Sorento CRM (the Sorento API key has no access "
        "to the work calendar); every hour counts as office hours."
    )


def test_an_unreadable_shape_reads_as_always_open_with_the_reason():
    read = office_hours.read_for_connection(
        _Conn(), {"apiKey": "k"}, now=_myt(23, 10),
        transport=_crm(calendar={**CALENDAR, "working_hours_start": "?"}),
    )
    assert read.hours is None and "could not be read" in read.error


def test_hint_shows_the_hours():
    read = office_hours.read_for_connection(_Conn(), {"apiKey": "k"}, now=_myt(23, 10), transport=_crm())
    assert office_hours.hint_text(read) == "Office hours from Sorento CRM: Monday - Friday, 9:00 am - 5:30 pm"


# ── the scheduler ───────────────────────────────────────────────────────────


def _http_task(session_factory, entity_type, *, due_at, reconcile_at=None):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.models import ETL_STATUS_ACTIVE
    from tests.test_autocount_scheduler import _company

    db = session_factory()
    company = _company(db, database_name=f"OH_{entity_type}")
    config = (
        db.query(AcEntityConfig)
        .filter(AcEntityConfig.company_id == company.id, AcEntityConfig.entity_type == entity_type)
        .one_or_none()
    )
    if config is None:
        config = AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type)
        db.add(config)
    config.source_impl = SOURCE_IMPL_AUTOCOUNT_HTTP
    config.etl_status = ETL_STATUS_ACTIVE
    config.source_config = {
        "connectionId": "irrelevant-to-the-sweep", "path": "/itembypage", "keyFields": ["ItemCode"],
        "watermarkField": None, "incrementalMinutes": 15,
        "reconcileMode": "dailyAt", "reconcileAt": "02:00", "reconcileTimezone": "Asia/Kuala_Lumpur",
    }
    config.next_incremental_at = due_at
    config.next_reconcile_at = reconcile_at
    db.commit()
    return db, company, config


@pytest.fixture
def calendar(monkeypatch):
    hours = office_hours.parse_work_calendar(CALENDAR, None, now=_myt(23, 10))
    state = {"read": office_hours.CalendarRead(hours=hours, error=None)}
    monkeypatch.setattr(office_hours, "read_for_company", lambda *a, **k: state["read"])
    return state


def test_in_office_hours_the_stock_runs_on_its_own_interval(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks

    now = _myt(23, 10)
    db, company, config = _http_task(session_factory, ENTITY_STOCK_BALANCE, due_at=now - timedelta(seconds=5))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    db.expire_all()
    assert db.get(AcEntityConfig, config.id).next_incremental_at == now + timedelta(minutes=15)


def test_outside_office_hours_the_stock_runs_hourly(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks

    now = _myt(23, 20)
    db, company, config = _http_task(session_factory, ENTITY_STOCK_BALANCE, due_at=now - timedelta(seconds=5))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    db.expire_all()
    assert db.get(AcEntityConfig, config.id).next_incremental_at == now + timedelta(minutes=60)


def test_outside_office_hours_products_wait_for_the_next_start(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _jobs_for

    now = _myt(27, 18)  # Friday evening
    db, company, config = _http_task(session_factory, ENTITY_PRODUCT, due_at=now - timedelta(seconds=5))
    result = sweep_etl_tasks(db, now=now, run_alerts=False)
    assert result["fired"] == 0
    assert _jobs_for(db, company.id, ENTITY_PRODUCT) == []
    db.expire_all()
    assert db.get(AcEntityConfig, config.id).next_incremental_at == _myt(30, 9)


def test_the_nightly_full_run_is_never_held_back(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks

    now = _myt(24, 2)
    db, _company, _config = _http_task(
        session_factory, ENTITY_PRODUCT, due_at=None, reconcile_at=now - timedelta(seconds=5),
    )
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1


def test_no_readable_calendar_changes_nothing(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks

    calendar["read"] = office_hours.CalendarRead(hours=None, error="no access")
    now = _myt(27, 22)
    db, _company, config = _http_task(session_factory, ENTITY_PRODUCT, due_at=now - timedelta(seconds=5))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    db.expire_all()
    assert db.get(AcEntityConfig, config.id).next_incremental_at == now + timedelta(minutes=15)


def test_direct_database_tasks_are_not_affected(session_factory, calendar):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _company, _task

    now = _myt(27, 22)
    db = session_factory()
    company = _company(db, database_name="OH_SQL")
    _task(db, company, next_incremental_at=now - timedelta(seconds=5))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1


# ── the Sorento connection page ─────────────────────────────────────────────


def test_sorento_connection_shows_the_office_hours_line(monkeypatch):
    from modules.autocount.sorento_provider import SorentoProvider

    monkeypatch.setattr(
        office_hours, "read_for_connection",
        lambda conn, creds, **kw: office_hours.CalendarRead(
            hours=office_hours.parse_work_calendar(CALENDAR, None, now=_myt(23, 10)), error=None,
        ),
    )

    class Conn(_Conn):
        credentials_json = None

    hints = SorentoProvider().field_hints(None, Conn())
    assert hints == {"baseUrl": {
        "kind": "text", "text": "Office hours from Sorento CRM: Monday - Friday, 9:00 am - 5:30 pm",
    }}


# ── security review round 1 ─────────────────────────────────────────────────


def test_a_private_crm_address_is_refused_before_the_key_is_sent():
    class Private(_Conn):
        config_json = {"baseUrl": "https://10.0.0.5:8080"}

    read = office_hours.read_for_connection(Private(), {"apiKey": "k"}, now=_myt(23, 10))
    assert read.hours is None
    assert read.error == "the Sorento base URL is not allowed"


def test_a_tick_reads_the_crm_at_most_a_few_times(monkeypatch):
    fetched = []
    monkeypatch.setattr(
        office_hours, "_fetch",
        lambda conn, *a, **k: fetched.append(conn.id) or office_hours.CalendarRead(hours=None, error="x"),
    )
    budget = office_hours.ReadBudget(2)
    for n in range(5):
        class C(_Conn):
            id = f"crm-{n}"
        office_hours.read_for_connection(C(), {"apiKey": "k"}, now=_myt(23, 10), budget=budget)
    assert len(fetched) == 2


def test_an_echoed_bad_value_is_cut_short():
    with pytest.raises(ValueError) as caught:
        office_hours.parse_work_calendar({**CALENDAR, "working_hours_start": "x" * 500}, None, now=_myt(23, 10))
    assert len(str(caught.value)) < 80


def test_the_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr(office_hours, "MAX_CACHE_ENTRIES", 3)
    monkeypatch.setattr(office_hours, "_fetch", lambda *a, **k: office_hours.CalendarRead(hours=None, error=None))
    for n in range(10):
        class C(_Conn):
            id = f"crm-{n}"
        office_hours.read_for_connection(C(), {"apiKey": "k"}, now=_myt(23, 10))
    assert len(office_hours._cache) <= 3
