"""Plan 13 S0 - Group C: AC-13-20 (floor 5), AC-13-21 (overlap guard pinned
at the new cadence). RED before the coder.

``MIN_INCREMENTAL_MINUTES_NO_WATERMARK`` is ``15`` today
(`services/etl_service.py:180`) - every test that expects the floor 5 fails
on the literal number, never a crash. The overlap guard mechanics
themselves are EXISTING, UNCHANGED code (AC-22-14) - `test_an_in_flight_
run_is_skipped_not_queued_behind`/`test_a_fresh_overlap_still_writes_one_
skip_row_per_tick` in `test_autocount_scheduler.py` already cover the
mechanism generically; what is new HERE is proving it holds at the new
5-minute floor specifically, which needs the floor to already be 5 to set
up (so these fail on the SAME wrong-floor reason, not a second one).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_RUNNING, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
from modules.autocount.models import (
    AcCompany,
    AcEntityConfig,
    AcSyncRun,
    ETL_STATUS_ACTIVE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_SKIPPED,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import (
    EtlService,
    EtlValidationError,
    MIN_INCREMENTAL_MINUTES_NO_WATERMARK,
)
from modules.autocount.sync import AUTOCOUNT_SYNC

from tests.test_s10_s5b_registration import _http_raw, _open_connection, _company

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


# ── AC-13-20: the floor constant itself ─────────────────────────────────────


def test_no_watermark_floor_constant_is_still_15_today():
    assert MIN_INCREMENTAL_MINUTES_NO_WATERMARK == 15, (
        "if this now reads 5, flip this pin to == 5 and move on - every "
        "other test below should already be green"
    )


def test_next_run_times_clamps_to_the_old_floor_not_5_yet():
    incremental, _reconcile = EtlService.next_run_times(
        {"incrementalMinutes": 4, "reconcileMode": "dailyAt", "reconcileAt": "02:00"}, now=NOW
    )
    assert incremental - NOW == timedelta(minutes=15), (
        "AC-13-20 wants this clamped to 5 for a no-watermark task; today it "
        "is still 15"
    )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_saving_incremental_minutes_4_still_422s_today(db):
    """Will keep 422ing after the floor drops (4 < 5 too) - this pins that
    the ERROR TEXT itself still names the OLD floor until the coder edits
    the constant, so a coder who only changes the frontend mirror and
    forgets the backend leaves this test red."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
            _http_raw(conn.id) | {"incrementalMinutes": 4},
        )
    message = exc_info.value.field_errors.get("incrementalMinutes", "")
    assert "5" in message, message


def test_saving_incremental_minutes_5_is_refused_until_the_floor_drops(db):
    """AC-13-20 - 5 minutes must be ACCEPTED once the floor is 5; today the
    floor is still 15, so this save 422s - the exact opposite of what the
    owner asked for (R3)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        _http_raw(conn.id) | {"incrementalMinutes": 5},
    )
    assert view.source_config["incrementalMinutes"] == 5


# ── AC-13-21: overlap guard pinned at the 5-minute cadence ──────────────────


def _active_task(db, company, conn, *, next_incremental_at) -> AcEntityConfig:
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        _http_raw(conn.id) | {"incrementalMinutes": 5},
    )
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_STOCK_BALANCE,
        )
        .one()
    )
    config.etl_status = ETL_STATUS_ACTIVE
    config.next_incremental_at = next_incremental_at
    config.next_reconcile_at = None
    db.commit()
    return config


def test_overlap_guard_at_5_minutes_writes_a_skip_row_and_advances_by_5(db):
    """AC-13-21 - needs `incrementalMinutes: 5` to actually SAVE first
    (blocked by AC-13-20 above today, so this is doubly red until the
    floor drops), then proves the EXISTING overlap guard re-arms by
    EXACTLY 5 minutes, not the old 15, at the new cadence."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _active_task(db, company, conn, next_incremental_at=NOW - timedelta(minutes=1))

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
        payload_json={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE},
    )
    db.add(job)
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 0, "skipped": 1, "failed": 0}

    skip_row = (
        db.query(AcSyncRun)
        .filter(
            AcSyncRun.tenant_id == DEFAULT_TENANT_ID,
            AcSyncRun.company_id == company.id,
            AcSyncRun.entity_type == ENTITY_STOCK_BALANCE,
            AcSyncRun.mode == RUN_MODE_SKIPPED,
        )
        .one()
    )
    assert skip_row is not None
    db.refresh(config)
    assert config.next_incremental_at - NOW == timedelta(minutes=5), (
        "the due time must advance by exactly the 5-minute cadence, not the "
        "old 15-minute floor"
    )


def test_fires_on_the_first_due_tick_after_the_in_flight_run_finishes(db):
    """AC-13-21 - once the blocking job is terminal, the NEXT due tick
    fires normally (the overlap guard is per-tick, not a lock the sweep
    waits out)."""
    from app.models.background_job import JOB_DONE

    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _active_task(db, company, conn, next_incremental_at=NOW - timedelta(minutes=1))

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_DONE,
        payload_json={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE},
    )
    db.add(job)
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 1, "skipped": 0, "failed": 0}
