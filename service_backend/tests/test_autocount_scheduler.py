"""The AutoCount ETL beat sweep (plan 22 S3, AC-22-13/14).

The sweep does NO extraction - these tests pin its due-selection, the
reconcile-wins-when-both-are-due rule, per-task failure isolation, and the
overlap guard's skipped run-history row. The underlying job it enqueues is
left to succeed or fail on its own (that pipeline is covered elsewhere,
``test_autocount_reconcile_push.py`` and ``test_autocount_etl_task_routes.py``)
- what matters here is purely the sweep's OWN selection/claim/enqueue logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    ETL_STATUS_PAUSED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    SOURCE_IMPL_AUTOCOUNT_READ,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcSyncRun,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sync import AUTOCOUNT_SYNC

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def _company(db, *, name="Sweep Co", database_name="SWEEP_DB") -> AcCompany:
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=database_name,
        company_name=name, name=name, is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


def _task(
    db,
    company,
    *,
    entity_type=ENTITY_CUSTOMER,
    etl_status=ETL_STATUS_ACTIVE,
    source_impl=SOURCE_IMPL_SQL_DB,
    next_incremental_at=None,
    next_reconcile_at=None,
) -> AcEntityConfig:
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == entity_type,
        )
        .one()
    )
    config.source_impl = source_impl
    config.etl_status = etl_status
    config.source_config = {
        "connectionId": "irrelevant-to-the-sweep",
        "query": "SELECT 1 AS acc_no",
        "keyColumns": ["acc_no"],
        "watermarkColumn": None,
        "comparedColumns": [],
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    config.next_incremental_at = next_incremental_at
    config.next_reconcile_at = next_reconcile_at
    db.commit()
    return config


def _jobs_for(db, company_id: str, entity_type: str):
    return (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.tenant_id == DEFAULT_TENANT_ID,
            BackgroundJob.type == AUTOCOUNT_SYNC,
            BackgroundJob.payload_json["companyId"].as_string() == company_id,
            BackgroundJob.payload_json["entityType"].as_string() == entity_type,
        )
        .all()
    )


# ── due-selection ─────────────────────────────────────────────────────────────


def test_an_incremental_due_task_fires_with_mode_incremental(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert len(jobs) == 1
    assert jobs[0].payload_json["mode"] == RUN_MODE_INCREMENTAL
    db.refresh(config)
    assert config.next_incremental_at > NOW
    db.close()


def test_a_reconcile_due_task_fires_with_mode_reconcile(session_factory):
    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_reconcile_at=NOW - timedelta(hours=1))

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert jobs[0].payload_json["mode"] == RUN_MODE_RECONCILE
    db.refresh(config)
    assert config.next_reconcile_at > NOW
    db.close()


def test_reconcile_wins_when_both_are_due(session_factory):
    db = session_factory()
    company = _company(db)
    _task(
        db, company,
        next_incremental_at=NOW - timedelta(minutes=1),
        next_reconcile_at=NOW - timedelta(hours=1),
    )

    sweep_etl_tasks(db, now=NOW)

    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert len(jobs) == 1
    assert jobs[0].payload_json["mode"] == RUN_MODE_RECONCILE
    db.close()


def test_only_the_due_field_is_advanced_not_the_other(session_factory):
    """Both are recomputed as PURE functions of `now`, but only the field(s)
    that were actually due get written back - the not-yet-due one must not
    silently reset."""
    db = session_factory()
    company = _company(db)
    untouched_reconcile_at = NOW + timedelta(hours=5)
    config = _task(
        db, company,
        next_incremental_at=NOW - timedelta(minutes=1),
        next_reconcile_at=untouched_reconcile_at,
    )

    sweep_etl_tasks(db, now=NOW)

    db.refresh(config)
    assert config.next_reconcile_at == untouched_reconcile_at


def test_a_draft_task_is_never_selected(session_factory):
    db = session_factory()
    company = _company(db)
    _task(
        db, company, etl_status=ETL_STATUS_DRAFT,
        next_incremental_at=NOW - timedelta(minutes=1),
    )
    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 0, "skipped": 0, "failed": 0}
    assert _jobs_for(db, company.id, ENTITY_CUSTOMER) == []


def test_a_paused_task_is_never_selected(session_factory):
    db = session_factory()
    company = _company(db)
    _task(
        db, company, etl_status=ETL_STATUS_PAUSED,
        next_incremental_at=NOW - timedelta(minutes=1),
    )
    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 0, "skipped": 0, "failed": 0}


def test_an_api_path_task_is_never_selected(session_factory):
    """The sweep is the sql_db pipeline only - the vendor-API path has no
    beat-driven schedule (D7 / slice 1 stays manual + workflow-triggered)."""
    db = session_factory()
    company = _company(db)
    _task(
        db, company, source_impl=SOURCE_IMPL_AUTOCOUNT_READ,
        etl_status=ETL_STATUS_ACTIVE,
        next_incremental_at=NOW - timedelta(minutes=1),
    )
    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 0, "skipped": 0, "failed": 0}


def test_a_not_yet_due_task_is_never_selected(session_factory):
    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW + timedelta(minutes=5))
    result = sweep_etl_tasks(db, now=NOW)
    assert result == {"fired": 0, "skipped": 0, "failed": 0}


# ── overlap guard (AC-22-14) ──────────────────────────────────────────────────


def test_an_in_flight_run_is_skipped_not_queued_behind(session_factory):
    from app.models.background_job import JOB_RUNNING

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
            payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
        )
    )
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 0, "skipped": 1, "failed": 0}
    # No SECOND job was queued behind the running one.
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1
    run = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company.id)
        .one()
    )
    assert run.mode == RUN_MODE_SKIPPED
    assert run.job_id is None
    assert run.skip_reason
    # The tick was still consumed - next_incremental_at advanced past `now`,
    # so the same overlap is not re-reported every single tick forever.
    db.refresh(config)
    assert config.next_incremental_at > NOW


def test_a_needs_review_job_does_NOT_count_as_in_flight(session_factory):
    """needs_review is parked on a human, not executing - the sweep must still
    fire (mirrors the manual Run-now rule, AC-22-14 §2.6)."""
    from app.models.background_job import JOB_NEEDS_REVIEW

    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_NEEDS_REVIEW,
            payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
        )
    )
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result["fired"] == 1
    assert result["skipped"] == 0


# ── per-task failure isolation ────────────────────────────────────────────────


def test_one_bad_task_never_stops_the_sweep_for_a_sibling(session_factory, monkeypatch):
    db = session_factory()
    company = _company(db)
    bad = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    company2 = _company(db, name="Sweep Co 2", database_name="SWEEP_DB_2")
    _task(db, company2, next_incremental_at=NOW - timedelta(minutes=1))

    import modules.autocount.scheduler as scheduler_module

    real_sweep_one = scheduler_module._sweep_one
    calls = {"n": 0}

    def flaky(db_, config, *, now):
        calls["n"] += 1
        if config.id == bad.id:
            raise RuntimeError("boom")
        return real_sweep_one(db_, config, now=now)

    monkeypatch.setattr(scheduler_module, "_sweep_one", flaky)

    result = sweep_etl_tasks(db, now=NOW)

    assert result["failed"] == 1
    assert result["fired"] == 1
    assert calls["n"] == 2
    # The GOOD task's job was still enqueued despite the bad one raising.
    assert len(_jobs_for(db, company2.id, ENTITY_CUSTOMER)) == 1


# ── two workers, one task (AC-22-14) ──────────────────────────────────────────


def test_a_second_beat_ticking_the_same_task_does_not_double_enqueue(session_factory):
    """The guarded claim UPDATE - simulated by ticking the SAME config twice
    with the SAME `now` on the same session (a second beat racing the first
    would see the row already advanced past `now` and lose the claim)."""
    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))

    first = sweep_etl_tasks(db, now=NOW)
    second = sweep_etl_tasks(db, now=NOW)

    assert first["fired"] == 1
    assert second == {"fired": 0, "skipped": 0, "failed": 0}
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1


def test_the_claim_itself_loses_the_race_when_called_directly_twice(session_factory):
    """N1 - exercise the actual `claimed == 0` branch inside `_sweep_one`
    (not just the outer "no second job" observation): call it TWICE with the
    exact SAME (stale, unrefreshed) config object and the same `now`, as two
    sibling beat workers racing on one already-fetched row would."""
    from modules.autocount.scheduler import _sweep_one

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))

    first = _sweep_one(db, config, now=NOW)
    # The claim UPDATE already advanced `next_incremental_at` past NOW in the
    # DB; `config` (this Python object) is stale/unrefreshed, so a second call
    # with it races into the lost-claim branch.
    second = _sweep_one(db, config, now=NOW)

    assert first == "fired"
    assert second == "not_due"
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1


# ── B3: deactivated Service / suspended-tenant isolation (S3 review) ──────────


def test_a_deactivated_service_task_is_never_swept(session_factory):
    """After a tenant deactivates the autocount Service (data kept, routes
    403), the beat must not keep extracting their production DB."""
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "autocount")

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 0, "skipped": 0, "failed": 0}
    assert _jobs_for(db, company.id, ENTITY_CUSTOMER) == []


def test_a_suspended_tenants_task_is_never_swept(session_factory):
    """A suspended tenant (``blocks_access``) must not keep pushing deletes
    with nobody able to see or stop it - same canonical lifecycle predicate
    the platform uses everywhere else (``Tenant.signin_allowed``)."""
    from app.models.tenant import Tenant

    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
    tenant.status.blocks_access = True
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 0, "skipped": 0, "failed": 0}
    assert _jobs_for(db, company.id, ENTITY_CUSTOMER) == []


def test_an_archived_tenants_task_is_never_swept(session_factory):
    from app.models.tenant import Tenant

    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
    tenant.status.is_archived = True
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 0, "skipped": 0, "failed": 0}
    assert _jobs_for(db, company.id, ENTITY_CUSTOMER) == []


# ── S3: stuck-job starvation ────────────────────────────────────────────────


def test_a_stale_stuck_job_stamps_the_error_once_and_stops_flooding_skip_rows(
    session_factory,
):
    """A job wedged 'running' forever must not produce a skip row on every
    tick (1440/day, no operator signal). Past `STALE_JOB_AFTER` it stamps
    `config.last_run_error` ONCE and every later tick is a silent no-op -
    ticking three times in a row must still leave exactly ONE skip run row."""
    from modules.autocount.scheduler import STALE_JOB_AFTER

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    stuck_job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type=AUTOCOUNT_SYNC,
        status="running",
        payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
        started_at=NOW - STALE_JOB_AFTER - timedelta(minutes=1),
    )
    db.add(stuck_job)
    db.commit()

    first = sweep_etl_tasks(db, now=NOW)
    # Re-arm the due time for two MORE real ticks (a recurring beat) - the
    # SAME stuck job is still in flight both times.
    config.next_incremental_at = NOW - timedelta(minutes=1)
    db.commit()
    second = sweep_etl_tasks(db, now=NOW)
    config.next_incremental_at = NOW - timedelta(minutes=1)
    db.commit()
    third = sweep_etl_tasks(db, now=NOW)

    assert first == {"fired": 0, "skipped": 1, "failed": 0}
    assert second == {"fired": 0, "skipped": 1, "failed": 0}
    assert third == {"fired": 0, "skipped": 1, "failed": 0}
    # No flood: the second and third ticks are silent no-ops (still counted
    # as skipped by the sweep's own accounting, but write nothing new).
    runs = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company.id)
        .all()
    )
    assert len(runs) == 1
    assert "appears stuck" in (runs[0].skip_reason or "")

    db.refresh(config)
    assert config.last_run_error and "appears stuck" in config.last_run_error
    assert config.last_run_error_code == "JOB_STUCK"


def test_a_fresh_overlap_still_writes_one_skip_row_per_tick(session_factory):
    """Control - a job that is genuinely still running (well under the stale
    threshold) keeps the existing per-tick skip-row behaviour."""
    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID,
            type=AUTOCOUNT_SYNC,
            status="running",
            payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
            started_at=NOW - timedelta(minutes=2),
        )
    )
    db.commit()

    first = sweep_etl_tasks(db, now=NOW)
    # Re-arm the due time (a real recurring tick) for a second sweep - the
    # SAME still-fresh overlapping job is still in flight.
    config.next_incremental_at = NOW - timedelta(minutes=1)
    db.commit()
    second = sweep_etl_tasks(db, now=NOW)

    assert first == {"fired": 0, "skipped": 1, "failed": 0}
    assert second == {"fired": 0, "skipped": 1, "failed": 0}
    runs = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company.id)
        .all()
    )
    assert len(runs) == 2
    assert all("appears stuck" not in (r.skip_reason or "") for r in runs)


# ── S4: post-claim enqueue failure must not be silent ─────────────────────────


def test_a_post_claim_enqueue_failure_stamps_the_task_error(session_factory, monkeypatch):
    """The claim UPDATE already committed (the due time already advanced) by
    the time `create_and_enqueue` runs - a failure there is a genuinely LOST
    tick, not a retried one. It must be visible on the task, not just a log
    line."""
    from app.jobs.service import JobService

    db = session_factory()
    company = _company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))

    def raising_enqueue(self, **kwargs):
        raise RuntimeError("boom - enqueue exploded")

    monkeypatch.setattr(JobService, "create_and_enqueue", raising_enqueue)

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 0, "skipped": 0, "failed": 1}
    # The claim itself is NOT lost silently - the config now shows why.
    db.refresh(config)
    assert config.last_run_error and "boom" in config.last_run_error
    assert config.last_run_error_code == "ENQUEUE_FAILED"
    # And the due time DID advance (the claim genuinely committed) - so the
    # loss is real, which is exactly why the error must be visible.
    assert config.next_incremental_at > NOW


def test_an_active_healthy_tenant_task_still_dispatches(session_factory):
    """Control - the B3 guard must not over-fire on the ordinary case."""
    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))

    result = sweep_etl_tasks(db, now=NOW)

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1
