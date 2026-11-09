"""SS-QUIET-HOURS - per-entity off hours for scheduled incremental syncs.

Owner 9 Nov: "configure the off time so it doesn't query the autocount when
there is no data change like at night, should be configurable per entity".

Inside a task's off-hours window a scheduled INCREMENTAL tick queues no job
(so AutoCount sees no query), writes no skip row, and re-arms to the window
end; the first tick at/after the end catches up from the watermark. The
reconcile keeps its own time; manual Run now is untouched (it never goes
through the sweep).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import AcEntityConfig, AcSyncRun
from modules.autocount.services.etl_service import (
    EtlService,
    in_quiet_hours,
    quiet_hours_end,
    validate_schedule,
)

MYT = timezone(timedelta(hours=8))


def _myt(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=MYT).astimezone(timezone.utc)


NIGHT = {
    "quietHoursEnabled": True,
    "quietHoursStart": "22:00",
    "quietHoursEnd": "07:00",
    "quietHoursTimezone": "Asia/Kuala_Lumpur",
}
SO_15S = {
    "watermarkColumn": "LastModified",
    "incrementalMinutes": 1,
    "incrementalSeconds": 15,
    "reconcileMode": "dailyAt",
    "reconcileAt": "02:00",
    "reconcileTimezone": "Asia/Kuala_Lumpur",
}


# ── the window (pure) ───────────────────────────────────────────────────────


def test_a_window_crossing_midnight_covers_the_night_only():
    assert in_quiet_hours(NIGHT, _myt(9, 22, 0))  # start is inclusive
    assert in_quiet_hours(NIGHT, _myt(9, 23, 30))
    assert in_quiet_hours(NIGHT, _myt(10, 0, 0))
    assert in_quiet_hours(NIGHT, _myt(10, 6, 59, 59))
    assert not in_quiet_hours(NIGHT, _myt(10, 7, 0))  # end is exclusive
    assert not in_quiet_hours(NIGHT, _myt(9, 12, 0))
    assert not in_quiet_hours(NIGHT, _myt(9, 21, 59, 59))


def test_a_same_day_window():
    lunch = {**NIGHT, "quietHoursStart": "12:00", "quietHoursEnd": "14:00"}
    assert in_quiet_hours(lunch, _myt(9, 13, 0))
    assert not in_quiet_hours(lunch, _myt(9, 14, 0))
    assert not in_quiet_hours(lunch, _myt(9, 23, 0))


def test_a_disabled_or_missing_window_never_applies():
    assert not in_quiet_hours({**NIGHT, "quietHoursEnabled": False}, _myt(9, 23, 0))
    assert not in_quiet_hours({}, _myt(9, 23, 0))
    # a corrupt stored value is treated as no window, never a crash
    assert not in_quiet_hours({**NIGHT, "quietHoursStart": "25:99"}, _myt(9, 23, 0))


def test_the_window_end_is_the_next_local_end_time():
    assert quiet_hours_end(NIGHT, _myt(9, 23, 0)) == _myt(10, 7, 0)
    assert quiet_hours_end(NIGHT, _myt(10, 3, 0)) == _myt(10, 7, 0)


def test_a_missing_zone_reads_myt():
    no_zone = {k: v for k, v in NIGHT.items() if k != "quietHoursTimezone"}
    assert in_quiet_hours(no_zone, _myt(9, 23, 0))
    assert quiet_hours_end(no_zone, _myt(9, 23, 0)) == _myt(10, 7, 0)


# ── next_run_times ──────────────────────────────────────────────────────────


def test_an_incremental_that_would_land_in_the_window_moves_to_its_end():
    incremental, reconcile = EtlService.next_run_times(
        {**SO_15S, **NIGHT}, now=_myt(9, 21, 59, 50)
    )
    assert incremental == _myt(10, 7, 0)
    # the reconcile keeps its own time, inside the window on purpose
    assert reconcile == _myt(10, 2, 0)


def test_an_incremental_outside_the_window_is_unchanged():
    now = _myt(10, 6, 59, 50)
    incremental, _ = EtlService.next_run_times({**SO_15S, **NIGHT}, now=now)
    assert incremental == now + timedelta(seconds=15)
    now = _myt(9, 12, 0)
    incremental, _ = EtlService.next_run_times({**SO_15S, **NIGHT}, now=now)
    assert incremental == now + timedelta(seconds=15)


def test_a_minutes_cadence_in_the_window_also_moves():
    masters = {"incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "03:00",
               "reconcileTimezone": "Asia/Kuala_Lumpur", **NIGHT}
    incremental, _ = EtlService.next_run_times(masters, now=_myt(9, 21, 50))
    assert incremental == _myt(10, 7, 0)


def test_without_off_hours_next_run_times_is_unchanged():
    now = _myt(9, 23, 0)
    incremental, _ = EtlService.next_run_times(SO_15S, now=now)
    assert incremental == now + timedelta(seconds=15)


# ── validation ──────────────────────────────────────────────────────────────

_BASE = {"incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00"}


def test_a_valid_window_is_kept():
    clean, errors = validate_schedule({**_BASE, **NIGHT}, has_watermark=True)
    assert errors == {}
    for key, value in NIGHT.items():
        assert clean[key] == value


def test_start_equal_to_end_is_refused():
    _, errors = validate_schedule(
        {**_BASE, **NIGHT, "quietHoursEnd": "22:00"}, has_watermark=True
    )
    assert "quietHoursEnd" in errors


def test_a_bad_time_is_refused_when_enabled():
    _, errors = validate_schedule({**_BASE, **NIGHT, "quietHoursStart": "9pm"}, has_watermark=True)
    assert "quietHoursStart" in errors
    _, errors = validate_schedule({**_BASE, **NIGHT, "quietHoursEnd": ""}, has_watermark=True)
    assert "quietHoursEnd" in errors


def test_a_disabled_window_with_blank_times_is_fine():
    clean, errors = validate_schedule(
        {**_BASE, "quietHoursEnabled": False, "quietHoursStart": "", "quietHoursEnd": None},
        has_watermark=True,
    )
    assert errors == {}
    assert clean["quietHoursEnabled"] is False


def test_an_unknown_zone_is_refused():
    _, errors = validate_schedule(
        {**_BASE, **NIGHT, "quietHoursTimezone": "Mars/Olympus"}, has_watermark=True
    )
    assert "quietHoursTimezone" in errors


def test_a_save_that_never_names_off_hours_keeps_the_keys_absent():
    clean, _ = validate_schedule(_BASE, has_watermark=True)
    assert "quietHoursEnabled" not in clean


def test_the_sql_task_save_carries_the_window():
    from modules.autocount.services.etl_service import validate_source_config
    from tests.test_autocount_documents import _HEADER_COLUMNS, _LINE_COLUMNS, _base_so_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER, _base_so_config(**NIGHT), _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert not any(k.startswith("quietHours") for k in errors), errors
    assert clean["quietHoursStart"] == "22:00"
    assert clean["quietHoursEnabled"] is True


def test_new_tasks_show_a_suggested_window_switched_off():
    from modules.autocount.services.etl_service import (
        default_http_source_config,
        default_source_config,
    )

    for config in (default_source_config(ENTITY_CUSTOMER), default_http_source_config()):
        assert config["quietHoursEnabled"] is False
        assert config["quietHoursStart"] == "22:00"
        assert config["quietHoursEnd"] == "07:00"


# ── the sweep ───────────────────────────────────────────────────────────────


def _night_task(session_factory, *, due_at, reconcile_at=None, db_name="QUIET_DB"):
    from tests.test_autocount_scheduler import _company, _task

    db = session_factory()
    company = _company(db, database_name=db_name)
    config = _task(db, company, next_incremental_at=due_at, next_reconcile_at=reconcile_at)
    config.source_config = {**config.source_config, **NIGHT}
    db.commit()
    return db, company, config


def test_a_tick_inside_the_window_queues_nothing_and_rearms_to_the_end(session_factory):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _jobs_for

    now = _myt(9, 23, 0)
    db, company, config = _night_task(session_factory, due_at=now - timedelta(seconds=5))
    result = sweep_etl_tasks(db, now=now, run_alerts=False)
    assert result["fired"] == 0 and result["skipped"] == 0
    assert _jobs_for(db, company.id, ENTITY_CUSTOMER) == []
    # no skip-row noise for a deliberate off window
    assert db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).count() == 0
    db.expire_all()
    row = db.get(AcEntityConfig, config.id)
    assert row.next_incremental_at == _myt(10, 7, 0)


def test_the_first_tick_after_the_window_catches_up(session_factory):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _jobs_for

    now = _myt(10, 7, 0, 5)
    db, company, _ = _night_task(session_factory, due_at=_myt(10, 7, 0))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert len(jobs) == 1
    assert jobs[0].payload_json["mode"] == "incremental"


def test_a_reconcile_due_inside_the_window_still_runs(session_factory):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _jobs_for

    now = _myt(10, 2, 0, 5)
    db, company, _ = _night_task(
        session_factory, due_at=now - timedelta(seconds=5), reconcile_at=_myt(10, 2, 0)
    )
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert [j.payload_json["mode"] for j in jobs] == ["reconcile"]


def test_a_task_without_off_hours_is_swept_as_before(session_factory):
    from modules.autocount.scheduler import sweep_etl_tasks
    from tests.test_autocount_scheduler import _company, _jobs_for, _task

    db = session_factory()
    company = _company(db, database_name="PLAIN_DB")
    now = _myt(9, 23, 0)
    _task(db, company, next_incremental_at=now - timedelta(seconds=5))
    assert sweep_etl_tasks(db, now=now, run_alerts=False)["fired"] == 1
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1


# ── save path ───────────────────────────────────────────────────────────────


def test_a_save_without_the_window_keeps_the_stored_one():
    from modules.autocount.services.etl_service import _with_stored_quiet_hours

    stored = {**_BASE, **NIGHT}
    assert _with_stored_quiet_hours(stored, dict(_BASE))["quietHoursStart"] == "22:00"
    sent = {**_BASE, "quietHoursEnabled": False, "quietHoursStart": "23:00"}
    assert _with_stored_quiet_hours(stored, sent)["quietHoursStart"] == "23:00"


def test_the_put_route_round_trips_the_window(client, session_factory):
    from tests.test_autocount_etl_routes import _auth, _company, _so_body, _sql_connection

    db = session_factory()
    conn = _sql_connection(db)
    company = _company(db)
    db.close()
    url = f"/autocount/companies/{company.id}/entities/sales_order/etl-task"
    response = client.put(url, json=_so_body(conn.id, **NIGHT), headers=_auth(client))
    assert response.status_code == 200, response.text
    got = response.json()["sourceConfig"]
    assert got["quietHoursEnabled"] is True
    assert (got["quietHoursStart"], got["quietHoursEnd"]) == ("22:00", "07:00")

    bad = client.put(
        url, json=_so_body(conn.id, **{**NIGHT, "quietHoursEnd": "22:00"}), headers=_auth(client)
    )
    assert bad.status_code == 422
    assert "quietHoursEnd" in bad.json()["detail"]["fieldErrors"]
