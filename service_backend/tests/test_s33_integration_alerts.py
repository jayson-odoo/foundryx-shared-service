"""Plan 33 (SS-INTEGRATION-ALERT) - the failure-alert evaluator, RED tests.

Written BEFORE the code from sprint-5/33-integration-run-failure-alert-acceptance-criteria.md
and the Phase 1 contract block. Every test carries its AC id. The clock is
always the ``now=`` argument; no wall clock, no SMTP, no WhatsApp.
"""
from __future__ import annotations

import re
import smtplib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.email_outbox import EmailOutbox
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_PAUSED,
    RUN_ABORTED,
    RUN_FAILED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    RUN_SUCCESS,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcSyncRun,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.company_service import CompanyService

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
OTHER_TENANT = "tenant-other-s33"
MANAGE = "autocount.companies.manage"
READ = "autocount.companies.read"


# ── seeding ──────────────────────────────────────────────────────────────────


def _evaluate(db, now=NOW) -> Dict[str, int]:
    from modules.autocount.alerts import evaluate_integration_alerts

    return evaluate_integration_alerts(db, now=now)


def _incident_model():
    from modules.autocount.models import AcTaskIncident

    return AcTaskIncident


def _open_incidents(db, config_id: Optional[str] = None) -> List[Any]:
    model = _incident_model()
    query = db.query(model).filter(model.closed_at.is_(None))
    if config_id is not None:
        query = query.filter(model.entity_config_id == config_id)
    return query.all()


def _all_incidents(db, config_id: str) -> List[Any]:
    model = _incident_model()
    return db.query(model).filter(model.entity_config_id == config_id).all()


def _company(
    db, *, name="Alert Co", database_name="ALERT_DB", tenant_id=DEFAULT_TENANT_ID
) -> AcCompany:
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    api = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=api.id, database_name=database_name,
        company_name=name, name=name, is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(tenant_id, company.id)
    db.commit()
    db.refresh(company)
    return company


def _task(
    db,
    company,
    *,
    entity_type=ENTITY_CUSTOMER,
    status=ETL_STATUS_ACTIVE,
    activated_ago=timedelta(minutes=30),
    minutes=15,
    tenant_id=DEFAULT_TENANT_ID,
    **alert_keys: Any,
) -> AcEntityConfig:
    """An ACTIVE sql_db task, activated ``activated_ago`` before NOW."""
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == tenant_id,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == entity_type,
        )
        .one()
    )
    config.source_impl = SOURCE_IMPL_SQL_DB
    config.etl_status = status
    config.activated_at = NOW - activated_ago
    config.source_config = {
        "connectionId": "irrelevant",
        "query": "SELECT 1 AS acc_no",
        "keyColumns": ["acc_no"],
        "watermarkColumn": None,
        "comparedColumns": [],
        "incrementalMinutes": minutes,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
        **alert_keys,
    }
    config.next_incremental_at = NOW + timedelta(hours=1)
    config.next_reconcile_at = NOW + timedelta(hours=10)
    db.commit()
    return config


def _run(
    db,
    company,
    *,
    tenant_id=DEFAULT_TENANT_ID,
    ago: timedelta,
    outcome: Optional[str] = RUN_FAILED,
    mode: str = RUN_MODE_INCREMENTAL,
    error: Optional[str] = "AutoCount answered HTTP 502 on page 3.",
    entity_type=ENTITY_CUSTOMER,
    finished: bool = True,
) -> AcSyncRun:
    finished_at = NOW - ago
    run = AcSyncRun(
        tenant_id=tenant_id,
        company_id=company.id,
        entity_type=entity_type,
        mode=mode,
        outcome=outcome if finished else None,
        error=error if outcome != RUN_SUCCESS or error else None,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at if finished else None,
    )
    db.add(run)
    db.commit()
    return run


def _fail(db, company, ago_minutes: int, **kw) -> AcSyncRun:
    return _run(db, company, ago=timedelta(minutes=ago_minutes), outcome=RUN_FAILED, **kw)


def _clean(db, company, ago_minutes: int, **kw) -> AcSyncRun:
    return _run(
        db, company, ago=timedelta(minutes=ago_minutes), outcome=RUN_SUCCESS, error=None, **kw
    )


def _emails(db) -> List[EmailOutbox]:
    return db.query(EmailOutbox).order_by(EmailOutbox.created_at, EmailOutbox.id).all()


def _only_recipients(db) -> None:
    """Deactivate every pre-seeded default-tenant user so a test controls the
    recipient set exactly."""
    for user in db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).all():
        user.status = UserStatus.INACTIVE.value
    db.commit()


def _user(
    db,
    email: str,
    *,
    perms: List[str],
    tenant_id: str = DEFAULT_TENANT_ID,
    status: str = UserStatus.ACTIVE.value,
    tz: Optional[str] = None,
) -> User:
    all_perms = PermissionRepository(db).list_all()
    role = Role(tenant_id=tenant_id, name=f"Role {email}", description="")
    role.permissions = [p for p in all_perms if p.key in perms]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password("limited1234"),
        name=email.split("@")[0],
        status=status,
        email_verified_at=sa.func.now(),
        timezone=tz,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    return user


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-co-s33", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


@pytest.fixture
def failing(session_factory):
    """One company, one ACTIVE customer task with two failed scheduled runs
    (it WILL trip the consecutive rule), and exactly one recipient."""
    db = session_factory()
    _only_recipients(db)
    _user(db, "admin-a@example.com", perms=[MANAGE])
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    yield db, company, config
    db.close()


# ── AC-33-01 consecutive rule ────────────────────────────────────────────────


def test_ac_33_01_two_failed_scheduled_runs_in_a_row_open_a_consecutive_incident(failing):
    db, _company_row, config = failing
    result = _evaluate(db)
    assert result["opened"] == 1
    rows = _open_incidents(db, config.id)
    assert len(rows) == 1
    assert rows[0].reason == "consecutive"
    assert rows[0].failed_runs == 2
    assert rows[0].tenant_id == DEFAULT_TENANT_ID
    assert rows[0].entity_type == ENTITY_CUSTOMER
    assert "502" in rows[0].last_error


def test_ac_33_01_one_failed_run_is_not_enough(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 5)
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_01_a_clean_run_inside_the_window_resets_the_count(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 25)
    _clean(db, company, 15, mode=RUN_MODE_INCREMENTAL)
    _fail(db, company, 5)
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_01_manual_failures_neither_count_nor_reset(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 25)
    _fail(db, company, 15, mode=RUN_MODE_MANUAL)
    _fail(db, company, 5)
    _evaluate(db)
    # the manual failure in between neither counts nor resets: 2 scheduled fails
    assert len(_open_incidents(db, config.id)) == 1

    other = _company(db, name="Manual Co", database_name="MANUAL_DB")
    other_config = _task(db, other)
    _fail(db, other, 25)
    _fail(db, other, 15, mode=RUN_MODE_MANUAL)
    _evaluate(db)
    # one scheduled failure + one manual failure is still only ONE counted failure
    assert _open_incidents(db, other_config.id) == []
    db.close()


def test_ac_33_01_skipped_ticks_neither_count_nor_reset(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 25)
    _run(db, company, ago=timedelta(minutes=15), outcome=None, mode=RUN_MODE_SKIPPED, error=None)
    _fail(db, company, 5)
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_01_an_aborted_run_is_neither_failed_nor_clean(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 25)
    _run(db, company, ago=timedelta(minutes=15), outcome=RUN_ABORTED, error=None)
    _fail(db, company, 5)
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_01_a_push_error_on_a_SUCCESS_run_counts_as_failed(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _run(db, company, ago=timedelta(minutes=20), outcome=RUN_SUCCESS,
         error="Sorento rejected the batch: HTTP 500")
    _run(db, company, ago=timedelta(minutes=5), outcome=RUN_SUCCESS,
         error="Sorento rejected the batch: HTTP 500", mode=RUN_MODE_RECONCILE)
    _evaluate(db)
    rows = _open_incidents(db, config.id)
    assert len(rows) == 1 and rows[0].reason == "consecutive"
    db.close()


def test_ac_33_01_an_orphaned_FAILED_run_counts_as_failed(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 20, error="Job orphaned: the worker restarted mid-run")
    _fail(db, company, 5, error="Job orphaned: the worker restarted mid-run")
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_01_the_failed_runs_in_a_row_threshold_is_per_integration(session_factory):
    db = session_factory()
    company = _company(db)
    three = _task(db, company, alertAfterFailedRuns=3)
    one = _task(db, company, entity_type=ENTITY_SUPPLIER, alertAfterFailedRuns=1)
    _fail(db, company, 20)
    _fail(db, company, 5)
    _fail(db, company, 4, entity_type=ENTITY_SUPPLIER)
    _evaluate(db)
    assert _open_incidents(db, three.id) == []
    assert len(_open_incidents(db, one.id)) == 1
    _fail(db, company, 1)
    _evaluate(db, now=NOW + timedelta(minutes=1))
    assert len(_open_incidents(db, three.id)) == 1
    db.close()


def test_ac_33_01_a_draft_or_paused_integration_never_opens(session_factory):
    db = session_factory()
    company = _company(db)
    paused = _task(db, company, status=ETL_STATUS_PAUSED)
    _fail(db, company, 20)
    _fail(db, company, 5)
    _evaluate(db)
    assert _open_incidents(db, paused.id) == []
    db.close()


# ── AC-33-02 stale rule ──────────────────────────────────────────────────────


def test_ac_33_02_no_clean_run_for_the_60_minute_floor_opens_a_stale_incident(session_factory):
    db = session_factory()
    company = _company(db)
    # 3 x 15 = 45 min is under the 60 min floor, so the window is 60 min
    config = _task(db, company, activated_ago=timedelta(minutes=61))
    _evaluate(db)
    rows = _open_incidents(db, config.id)
    assert len(rows) == 1 and rows[0].reason == "stale"
    db.close()


def test_ac_33_02_just_inside_the_floor_does_not_trip(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, activated_ago=timedelta(minutes=59))
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_02_the_window_is_the_multiple_of_the_interval_above_the_floor(session_factory):
    db = session_factory()
    company = _company(db)
    # 3 x 30 = 90 min
    inside = _task(db, company, minutes=30, activated_ago=timedelta(minutes=80))
    outside = _task(
        db, company, entity_type=ENTITY_SUPPLIER, minutes=30, activated_ago=timedelta(minutes=91)
    )
    _evaluate(db)
    assert _open_incidents(db, inside.id) == []
    assert len(_open_incidents(db, outside.id)) == 1
    db.close()


def test_ac_33_02_the_stale_multiple_is_per_integration(session_factory):
    db = session_factory()
    company = _company(db)
    # 2 x 60 = 120 min window with alertStaleMultiple=2
    config = _task(db, company, minutes=60, alertStaleMultiple=2, activated_ago=timedelta(minutes=110))
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    _evaluate(db, now=NOW + timedelta(minutes=11))
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_02_the_clock_starts_at_the_later_of_last_clean_and_activation(session_factory):
    db = session_factory()
    company = _company(db)
    # Activated long ago; the last clean run was 30 min ago: not stale
    fresh = _task(db, company, activated_ago=timedelta(days=3))
    _clean(db, company, 30)
    _evaluate(db)
    assert _open_incidents(db, fresh.id) == []

    # Last clean run 61 min ago, activated long before it: stale
    other = _company(db, name="Stale Co", database_name="STALE_DB")
    stale = _task(db, other, activated_ago=timedelta(days=3))
    _clean(db, other, 61)
    _evaluate(db)
    rows = _open_incidents(db, stale.id)
    assert len(rows) == 1 and rows[0].reason == "stale"

    # Clean run 90 min ago but RE-activated 5 min ago: the clock restarts
    third = _company(db, name="Resumed Co", database_name="RESUMED_DB")
    resumed = _task(db, third, activated_ago=timedelta(minutes=5))
    _clean(db, third, 90)
    _evaluate(db)
    assert _open_incidents(db, resumed.id) == []
    db.close()


def test_ac_33_02_a_freshly_activated_integration_with_no_run_does_not_trip_at_once(
    session_factory,
):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, activated_ago=timedelta(minutes=1))
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    db.close()


def test_ac_33_02_a_wedged_run_that_never_finishes_trips_the_stale_rule(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, activated_ago=timedelta(hours=3))
    _run(db, company, ago=timedelta(hours=2), outcome=None, error=None, finished=False)
    _evaluate(db)
    rows = _open_incidents(db, config.id)
    assert len(rows) == 1 and rows[0].reason == "stale"
    db.close()


# ── AC-33-03 sweep hook + isolation ──────────────────────────────────────────


def test_ac_33_03_the_ETL_sweep_runs_the_check(failing):
    db, _company_row, config = failing
    sweep_etl_tasks(db, now=NOW)
    assert len(_open_incidents(db, config.id)) == 1


def test_ac_33_03_an_evaluator_crash_never_changes_the_sweeps_return_value(
    session_factory, monkeypatch
):
    import modules.autocount.alerts as alerts
    import modules.autocount.scheduler as scheduler

    def boom(*_a, **_k):
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr(alerts, "evaluate_integration_alerts", boom)
    monkeypatch.setattr(scheduler, "evaluate_integration_alerts", boom, raising=False)

    db = session_factory()
    company = _company(db)
    config = _task(db, company)
    config.next_incremental_at = NOW - timedelta(minutes=1)
    db.commit()
    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    db.close()


def test_ac_33_03_one_integrations_error_does_not_stop_the_others(session_factory, monkeypatch):
    from app.services.email_service import email_service

    db = session_factory()
    _only_recipients(db)
    _user(db, "iso@example.com", perms=[MANAGE])
    bad = _company(db, name="Bad Co", database_name="BAD_DB")
    good = _company(db, name="Good Co", database_name="GOOD_DB")
    bad_cfg = _task(db, bad)
    good_cfg = _task(db, good)
    for company in (bad, good):
        _fail(db, company, 20)
        _fail(db, company, 5)

    real = email_service.enqueue_raw

    def flaky(db_, tenant_id, to_email, subject, *a, **k):
        if "Bad Co" in subject:
            raise RuntimeError("enqueue exploded for one integration")
        return real(db_, tenant_id, to_email, subject, *a, **k)

    monkeypatch.setattr(email_service, "enqueue_raw", flaky)
    result = _evaluate(db)
    assert result["failed"] >= 1
    assert len(_open_incidents(db, good_cfg.id)) == 1
    assert any("Good Co" in e.subject for e in _emails(db))
    assert not any("Bad Co" in e.subject for e in _emails(db))
    del bad_cfg
    db.close()


def _tenant_failing(db, tenant_id: str, email: str):
    """A failing ACTIVE integration for ``tenant_id`` plus one manager."""
    _user(db, email, perms=[MANAGE], tenant_id=tenant_id)
    company = _company(db, name=f"Co {tenant_id}", database_name=f"DB_{tenant_id}"[:30],
                       tenant_id=tenant_id)
    config = _task(db, company, tenant_id=tenant_id)
    for ago in (20, 5):
        _run(db, company, ago=timedelta(minutes=ago), outcome=RUN_FAILED, tenant_id=tenant_id)
    return company, config


def test_ac_33_03_a_second_tenants_failing_integration_opens_in_the_same_call(session_factory):
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    db = session_factory()
    _only_recipients(db)
    _other_tenant(db)
    mine = _company(db)
    my_config = _task(db, mine)
    _fail(db, mine, 20)
    _fail(db, mine, 5)
    _user(db, "mine-s33@example.com", perms=[MANAGE])
    module = db.query(Module).filter(Module.name == "autocount").one()
    db.add(TenantModule(tenant_id=OTHER_TENANT, module_id=module.id,
                        status=MODULE_STATUS_ACTIVE, installed_version="1.0.0"))
    db.commit()
    _theirs, their_config = _tenant_failing(db, OTHER_TENANT, "theirs-s33@example.com")

    result = _evaluate(db)
    assert result["opened"] == 2
    assert len(_open_incidents(db, my_config.id)) == 1
    assert len(_open_incidents(db, their_config.id)) == 1
    by_tenant = {e.tenant_id: e.to_email for e in _emails(db)}
    assert by_tenant == {DEFAULT_TENANT_ID: "mine-s33@example.com",
                         OTHER_TENANT: "theirs-s33@example.com"}
    db.close()


def test_ac_33_03_a_deactivated_service_tenant_gets_no_incident_and_no_email(session_factory):
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    _only_recipients(db)
    _user(db, "inactive-svc@example.com", perms=[MANAGE])
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "autocount")
    result = _evaluate(db)
    assert result["opened"] == 0
    assert _open_incidents(db, config.id) == []
    assert _emails(db) == []
    db.close()


@pytest.mark.parametrize("flag", ["blocks_access", "is_archived"])
def test_ac_33_03_a_suspended_or_archived_tenant_gets_no_incident_and_no_email(
    session_factory, flag
):
    db = session_factory()
    _only_recipients(db)
    _user(db, "suspended@example.com", perms=[MANAGE])
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    setattr(tenant.status, flag, True)
    db.commit()
    result = _evaluate(db)
    assert result["opened"] == 0
    assert _open_incidents(db, config.id) == []
    assert _emails(db) == []
    db.close()


# ── AC-33-04 alerts off ──────────────────────────────────────────────────────


def test_ac_33_04_alerts_off_opens_no_incident(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, alertsEnabled=False)
    _fail(db, company, 20)
    _fail(db, company, 5)
    _evaluate(db)
    assert _open_incidents(db, config.id) == []
    assert _emails(db) == []
    db.close()


def test_ac_33_04_switching_alerts_off_closes_an_open_incident_silently(failing):
    db, _company_row, config = failing
    _evaluate(db)
    assert len(_open_incidents(db, config.id)) == 1
    sent = len(_emails(db))

    config.source_config = {**config.source_config, "alertsEnabled": False}
    db.commit()
    result = _evaluate(db, now=NOW + timedelta(minutes=1))
    assert _open_incidents(db, config.id) == []
    assert result["closed"] == 1
    assert len(_emails(db)) == sent


# ── AC-33-05 one alert, 4-hourly reminders ───────────────────────────────────


def test_ac_33_05_opening_sends_one_alert_per_recipient_and_no_repeat(failing):
    db, _company_row, _config = failing
    _evaluate(db)
    assert len(_emails(db)) == 1
    _evaluate(db, now=NOW + timedelta(minutes=2))
    _evaluate(db, now=NOW + timedelta(hours=1))
    assert len(_emails(db)) == 1


def test_ac_33_05_a_reminder_follows_only_after_four_hours_and_then_every_four(failing):
    from modules.autocount.alerts import REMINDER_INTERVAL

    assert REMINDER_INTERVAL == timedelta(hours=4)
    db, _company_row, config = failing
    _evaluate(db)
    _evaluate(db, now=NOW + timedelta(hours=3, minutes=59))
    assert len(_emails(db)) == 1

    result = _evaluate(db, now=NOW + timedelta(hours=4, minutes=1))
    assert result["reminded"] == 1
    emails = _emails(db)
    assert len(emails) == 2
    assert emails[1].subject.startswith("Still failing: Customer (Alert Co), ")
    # same check again: nothing until 4 h after the REMINDER
    _evaluate(db, now=NOW + timedelta(hours=4, minutes=3))
    _evaluate(db, now=NOW + timedelta(hours=8))
    assert len(_emails(db)) == 2
    _evaluate(db, now=NOW + timedelta(hours=8, minutes=2))
    assert len(_emails(db)) == 3
    rows = _open_incidents(db, config.id)
    assert len(rows) == 1 and rows[0].notices_sent == 3


# ── AC-33-06 recovered ───────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", [RUN_MODE_INCREMENTAL, RUN_MODE_MANUAL])
def test_ac_33_06_a_clean_run_closes_the_incident_and_sends_one_recovered_email(failing, mode):
    db, company, config = failing
    _evaluate(db)
    assert len(_emails(db)) == 1
    _run(db, company, ago=timedelta(minutes=-1), outcome=RUN_SUCCESS, error=None, mode=mode)

    result = _evaluate(db, now=NOW + timedelta(minutes=2))
    assert result["recovered"] == 1
    assert _open_incidents(db, config.id) == []
    closed = _all_incidents(db, config.id)
    assert len(closed) == 1 and closed[0].close_reason == "recovered"
    emails = _emails(db)
    assert len(emails) == 2
    assert emails[1].subject == "Customer (Alert Co) is running again"

    _evaluate(db, now=NOW + timedelta(minutes=3))
    assert len(_emails(db)) == 2


def test_ac_33_06_a_failed_manual_run_does_not_close_the_incident(failing):
    db, company, config = failing
    _evaluate(db)
    _fail(db, company, -1, mode=RUN_MODE_MANUAL)
    _evaluate(db, now=NOW + timedelta(minutes=2))
    assert len(_open_incidents(db, config.id)) == 1
    assert len(_emails(db)) == 1


# ── AC-33-07 pause / deactivate ──────────────────────────────────────────────


def test_ac_33_07_pausing_closes_the_incident_with_no_email(failing):
    db, _company_row, config = failing
    _evaluate(db)
    sent = len(_emails(db))
    config.etl_status = ETL_STATUS_PAUSED
    db.commit()
    result = _evaluate(db, now=NOW + timedelta(minutes=1))
    assert result["closed"] == 1
    assert _open_incidents(db, config.id) == []
    assert _all_incidents(db, config.id)[0].close_reason == "paused"
    assert len(_emails(db)) == sent


def test_ac_33_07_deactivating_closes_the_incident_with_no_email(failing):
    db, _company_row, config = failing
    _evaluate(db)
    sent = len(_emails(db))
    config.enabled = False
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=1))
    assert _open_incidents(db, config.id) == []
    assert _all_incidents(db, config.id)[0].close_reason in ("disabled", "paused")
    assert len(_emails(db)) == sent


def test_ac_33_07_re_activating_starts_fresh(failing):
    db, _company_row, config = failing
    _evaluate(db)
    config.etl_status = ETL_STATUS_PAUSED
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=1))
    sent = len(_emails(db))

    config.etl_status = ETL_STATUS_ACTIVE
    config.activated_at = NOW + timedelta(minutes=2)
    db.commit()
    _evaluate(db, now=NOW + timedelta(minutes=3))
    # the old failed runs predate the resume: the rules must trip again
    assert _open_incidents(db, config.id) == []
    assert len(_emails(db)) == sent


# ── AC-33-08 recipients ──────────────────────────────────────────────────────


def test_ac_33_08_recipients_are_same_tenant_active_managers_plus_also_email(session_factory):
    db = session_factory()
    _only_recipients(db)
    _other_tenant(db)
    _user(db, "mgr@example.com", perms=[MANAGE])
    _user(db, "Dupe@Example.com", perms=[MANAGE])
    _user(db, "inactive-mgr@example.com", perms=[MANAGE], status=UserStatus.INACTIVE.value)
    _user(db, "reader@example.com", perms=[READ])
    _user(db, "outsider@other.com", perms=[MANAGE], tenant_id=OTHER_TENANT)
    company = _company(db)
    config = _task(
        db, company,
        alertEmails=["EXTRA@example.com", "dupe@example.com", "extra@example.com", "mgr@EXAMPLE.com"],
    )
    _fail(db, company, 20)
    _fail(db, company, 5)
    _evaluate(db)

    addresses = [e.to_email.lower() for e in _emails(db)]
    assert sorted(addresses) == ["dupe@example.com", "extra@example.com", "mgr@example.com"]
    assert all(e.tenant_id == DEFAULT_TENANT_ID for e in _emails(db))
    assert len(_open_incidents(db, config.id)) == 1
    db.close()


def test_ac_33_08_no_recipients_still_opens_the_incident_without_email(session_factory):
    db = session_factory()
    _only_recipients(db)
    company = _company(db)
    config = _task(db, company)
    _fail(db, company, 20)
    _fail(db, company, 5)
    result = _evaluate(db)
    assert result["opened"] == 1
    assert len(_open_incidents(db, config.id)) == 1
    assert _emails(db) == []
    db.close()


# ── AC-33-09 wording ─────────────────────────────────────────────────────────


def test_ac_33_09_the_consecutive_alert_subject_and_body(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "words@example.com", perms=[MANAGE])
    company = _company(db, name="V Soft Trading", database_name="AED_VSOFT")
    config = _task(db, company)
    _fail(db, company, 20, error="AutoCount answered HTTP 502 on page 3.\nstack line two")
    _fail(db, company, 5, error="AutoCount answered HTTP 502 on page 3.\nstack line two")
    _evaluate(db)
    mail = _emails(db)[0]
    assert mail.subject == "Customer (V Soft Trading) has failed 2 runs in a row"
    for body in (mail.html_body, mail.text_body):
        assert "V Soft Trading" in body
        assert "AED_VSOFT" in body
        assert "AutoCount answered HTTP 502 on page 3." in body
        assert "stack line two" not in body
        assert f"/autocount/companies/{company.id}/entities/customer?tab=runs" in body
        assert "foundryx" not in body.lower()
        assert "UTC" in body
    assert "foundryx" not in mail.subject.lower()
    del config
    db.close()


def test_ac_33_09_the_stale_alert_subject(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "stale@example.com", perms=[MANAGE])
    company = _company(db, name="V Soft Trading", database_name="AED_VSOFT")
    _task(db, company, activated_ago=timedelta(minutes=90))
    _evaluate(db)
    assert _emails(db)[0].subject.startswith(
        "Customer (V Soft Trading) has had no successful run since "
    )
    db.close()


def test_ac_33_09_the_reminder_subject_carries_the_failed_run_count(failing):
    db, _company_row, _config = failing
    _evaluate(db)
    _evaluate(db, now=NOW + timedelta(hours=4, minutes=1))
    subject = _emails(db)[1].subject
    assert subject.startswith("Still failing: Customer (Alert Co), 2 failed runs since ")


def test_ac_33_09_times_use_the_recipients_timezone_with_the_zone_shown(session_factory):
    db = session_factory()
    _only_recipients(db)
    _user(db, "kl@example.com", perms=[MANAGE], tz="Asia/Kuala_Lumpur")
    company = _company(db)
    _task(db, company)
    _fail(db, company, 20)  # 11:40 UTC = 19:40 in Kuala Lumpur
    _fail(db, company, 5)
    _evaluate(db)
    body = _emails(db)[0].text_body
    assert re.search(r"19:(39|40)", body)
    assert "UTC" not in body
    assert any(zone in body for zone in ("MYT", "+08", "Asia/Kuala_Lumpur", "UTC+8", "GMT+8"))
    db.close()


# ── AC-33-10 outbox only ─────────────────────────────────────────────────────


def test_ac_33_10_alerts_go_through_the_outbox_and_never_touch_smtp(failing, monkeypatch):
    def no_smtp(*_a, **_k):
        raise AssertionError("an alert must go through the outbox, never SMTP directly")

    monkeypatch.setattr(smtplib, "SMTP", no_smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_smtp)
    db, _company_row, _config = failing
    _evaluate(db)
    rows = _emails(db)
    assert len(rows) == 1
    assert rows[0].tenant_id == DEFAULT_TENANT_ID
    assert rows[0].to_email == "admin-a@example.com"


def test_ac_33_10_the_contract_constants_exist():
    from modules.autocount import alerts

    assert alerts.DEFAULT_ALERT_AFTER_FAILED_RUNS == 2
    assert alerts.DEFAULT_ALERT_STALE_MULTIPLE == 3
    assert alerts.STALE_FLOOR_MINUTES == 60
    assert alerts.MAX_ALERT_EMAILS == 10
