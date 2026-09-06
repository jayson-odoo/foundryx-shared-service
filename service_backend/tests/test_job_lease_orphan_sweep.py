"""Job lease: heartbeat + orphan sweep (prod incident 2026-09-07 16:59Z).

A purchase_order sync job was mid-run when the blue/green deploy stopped the
old colour; the container died, the ``background_jobs`` row stayed
``running`` forever, its ``ac_sync_run`` stayed open, and every scheduler
tick since was "skipped: a run for this task was still in progress" - after
60 minutes the scheduler only stamped JOB_STUCK and paused. No heartbeat, no
startup sweep; manual SQL was the only way out.

Contract:
1. ``BackgroundJob.heartbeat_at`` (nullable), refreshed by the autocount run
   loop at least once per page via ``JobService.heartbeat(job_id)``.
2. ``JobService.fail_orphaned_running_jobs(*, older_than, now=None)``: every
   ``running`` job whose ``heartbeat_at`` (or ``started_at`` when NULL) is
   older than the threshold -> ``failed`` + INTERRUPTED_MESSAGE +
   ``finished_at``; its open ``ac_sync_run`` -> outcome FAILED, same error,
   ``finished_at``/``duration_ms``; staged rows untouched; returns the count;
   idempotent. Called from app startup.
3. The scheduler releases a stale in-flight job through the same sweep and
   FIRES the tick instead of skipping; a fresh in-flight job still skips.

Fixtures are the bulk-load rig (a real paged run) and the scheduler suite's
company/task helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
import sqlalchemy as sa

from app.config import settings
from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_RUNNING,
    BackgroundJob,
)
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    RUN_FAILED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_SKIPPED,
    STAGED,
    AcStagedRecord,
    AcSyncRun,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.sync import AUTOCOUNT_SYNC
from tests.test_autocount_bulk_load import (  # noqa: F401 - fixtures re-exported
    _clean_runtime,
    _insert_rows,
    _make_rig,
    _rows,
    _run,
    _run_row,
    consumer,
)
from tests.test_autocount_scheduler import NOW, _jobs_for, _task
from tests.test_autocount_scheduler import _company as _sched_company

THRESHOLD = timedelta(minutes=15)
INTERRUPTED = (
    "Interrupted: the worker stopped (deploy or crash) before this run finished; "
    "the next run re-offers its staged rows"
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _job(
    db, *, status: str, started_ago: Optional[timedelta], heartbeat_ago: Optional[timedelta],
    now: datetime, company_id: str = "co-1",
) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=status,
        payload_json={"companyId": company_id, "entityType": ENTITY_CUSTOMER},
        started_at=(now - started_ago) if started_ago is not None else None,
    )
    if heartbeat_ago is not None:
        job.heartbeat_at = now - heartbeat_ago
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _open_run(db, job: BackgroundJob, *, started_at: datetime, company_id: str = "co-1") -> AcSyncRun:
    run = AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_CUSTOMER,
        job_id=job.id, mode=RUN_MODE_INCREMENTAL, started_at=started_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ── (1) the column exists and the paged run loop refreshes it ───────────────


def test_background_job_has_a_nullable_heartbeat_column():
    column = BackgroundJob.__table__.c.get("heartbeat_at")
    assert column is not None, "BackgroundJob.heartbeat_at is missing"
    assert column.nullable is True


def test_a_paged_run_refreshes_the_heartbeat_between_pages(session_factory, monkeypatch, consumer):
    """Three pages of two rows; the heartbeat observed at the start of page 2
    and page 3 must be set and non-decreasing, and must have advanced at
    least once across the run."""
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(6))

    observer = session_factory()
    seen: List[Optional[str]] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        # The page's SELECT is about to run: read the job's heartbeat on a
        # SEPARATE session (the heartbeat is committed in its own short
        # transaction, never the run's).
        seen.append(
            observer.execute(
                sa.text(
                    "SELECT heartbeat_at FROM background_jobs WHERE status = :s "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": JOB_RUNNING},
            ).scalar()
        )
        observer.rollback()

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE, job.error
    run = _run_row(db, company_id, job.id)
    assert run.rows_scanned == 6

    assert len(seen) >= 3, f"expected three page SELECTs, saw {len(seen)}"
    later_pages = seen[1:]
    assert all(v is not None for v in later_pages), (
        f"heartbeat must be set once the first page has been processed: {seen}"
    )
    assert later_pages == sorted(later_pages)
    db.refresh(job)
    assert job.heartbeat_at is not None
    assert len(set(later_pages + [str(job.heartbeat_at)])) >= 2, "the heartbeat never advanced"
    db.close()


# ── (2) the orphan sweep ────────────────────────────────────────────────────


def test_sweep_fails_only_stale_running_jobs_and_closes_their_open_runs(db):
    now = datetime.now(timezone.utc)
    stale_by_started = _job(db, status=JOB_RUNNING, started_ago=timedelta(minutes=30), heartbeat_ago=None, now=now)
    stale_run = _open_run(db, stale_by_started, started_at=now - timedelta(minutes=30))
    stale_by_heartbeat = _job(db, status=JOB_RUNNING, started_ago=timedelta(hours=3), heartbeat_ago=timedelta(minutes=20), now=now)
    fresh_heartbeat = _job(db, status=JOB_RUNNING, started_ago=timedelta(hours=3), heartbeat_ago=timedelta(minutes=1), now=now)
    fresh_run = _open_run(db, fresh_heartbeat, started_at=now - timedelta(hours=3))
    needs_review = _job(db, status=JOB_NEEDS_REVIEW, started_ago=timedelta(days=2), heartbeat_ago=None, now=now)
    done = _job(db, status=JOB_DONE, started_ago=timedelta(days=2), heartbeat_ago=None, now=now)
    staged = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id="co-1", entity_type=ENTITY_CUSTOMER,
        job_id=stale_by_started.id, source_ref="AED:1", doc_no="1",
        canonical_json={"code": "1"}, status=STAGED,
    )
    db.add(staged)
    db.commit()

    count = JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD)
    db.expire_all()

    assert count == 2
    for job in (stale_by_started, stale_by_heartbeat):
        fresh = db.get(BackgroundJob, job.id)
        assert fresh.status == JOB_FAILED
        assert fresh.error == INTERRUPTED
        assert fresh.finished_at is not None
    assert db.get(BackgroundJob, fresh_heartbeat.id).status == JOB_RUNNING
    assert db.get(BackgroundJob, needs_review.id).status == JOB_NEEDS_REVIEW
    assert db.get(BackgroundJob, done.id).status == JOB_DONE

    closed = db.get(AcSyncRun, stale_run.id)
    assert closed.outcome == RUN_FAILED
    assert closed.error == INTERRUPTED
    assert closed.finished_at is not None
    assert closed.duration_ms is not None and closed.duration_ms >= 0
    still_open = db.get(AcSyncRun, fresh_run.id)
    assert still_open.finished_at is None and still_open.outcome is None

    # Staged rows are untouched - they re-offer on the next run.
    assert db.get(AcStagedRecord, staged.id).status == STAGED

    assert JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD) == 0


def test_sweep_with_a_null_heartbeat_falls_back_to_started_at(db):
    now = datetime.now(timezone.utc)
    young = _job(db, status=JOB_RUNNING, started_ago=timedelta(minutes=5), heartbeat_ago=None, now=now)
    old = _job(db, status=JOB_RUNNING, started_ago=timedelta(minutes=16), heartbeat_ago=None, now=now)

    assert JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD) == 1
    db.expire_all()
    assert db.get(BackgroundJob, young.id).status == JOB_RUNNING
    assert db.get(BackgroundJob, old.id).status == JOB_FAILED


def test_sweep_accepts_an_injected_now_for_the_scheduler(db):
    """The scheduler ticks with an injected ``now``; the sweep it calls must
    judge staleness against that same clock."""
    old = _job(db, status=JOB_RUNNING, started_ago=timedelta(minutes=16), heartbeat_ago=None, now=NOW)
    fresh = _job(db, status=JOB_RUNNING, started_ago=timedelta(minutes=1), heartbeat_ago=None, now=NOW)

    assert JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD, now=NOW) == 1
    db.expire_all()
    assert db.get(BackgroundJob, old.id).status == JOB_FAILED
    assert db.get(BackgroundJob, fresh.id).status == JOB_RUNNING


# ── (3) the scheduler releases a stale job and fires ────────────────────────


def test_a_stale_in_flight_job_is_released_and_the_tick_fires(session_factory):
    db = session_factory()
    company = _sched_company(db)
    config = _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    stuck = _job(
        db, status=JOB_RUNNING, started_ago=timedelta(minutes=20), heartbeat_ago=None,
        now=NOW, company_id=company.id,
    )
    open_run = _open_run(db, stuck, started_at=NOW - timedelta(minutes=20), company_id=company.id)

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    released = db.get(BackgroundJob, stuck.id)
    assert released.status == JOB_FAILED
    assert released.error == INTERRUPTED
    closed = db.get(AcSyncRun, open_run.id)
    assert closed.outcome == RUN_FAILED and closed.finished_at is not None
    # A NEW job was created for this tick.
    jobs = _jobs_for(db, company.id, ENTITY_CUSTOMER)
    assert len(jobs) == 2
    assert any(j.id != stuck.id for j in jobs)
    # No JOB_STUCK pause, no skip row for this tick.
    db.refresh(config)
    assert config.last_run_error_code != "JOB_STUCK"
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company.id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .count()
    )
    assert skip_rows == 0
    db.close()


def test_a_fresh_in_flight_job_is_still_skipped(session_factory):
    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    fresh = _job(
        db, status=JOB_RUNNING, started_ago=timedelta(hours=2), heartbeat_ago=timedelta(minutes=1),
        now=NOW, company_id=company.id,
    )

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 0, "skipped": 1, "failed": 0}
    assert db.get(BackgroundJob, fresh.id).status == JOB_RUNNING
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company.id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .all()
    )
    assert len(skip_rows) == 1
    assert "still in progress" in (skip_rows[0].skip_reason or "")
    db.close()


# ── (4) the sweep runs at app startup ───────────────────────────────────────


def test_startup_runs_the_orphan_sweep_with_the_15_minute_threshold(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls: List[dict] = []

    def recorder(self, *, older_than, now=None):
        calls.append({"older_than": older_than})
        return 0

    monkeypatch.setattr(JobService, "fail_orphaned_running_jobs", recorder, raising=False)
    with TestClient(app):
        pass

    assert calls, "app startup must invoke JobService.fail_orphaned_running_jobs"
    assert calls[0]["older_than"] == THRESHOLD


def test_a_failing_startup_sweep_never_blocks_boot(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    def boom(self, *, older_than, now=None):
        raise RuntimeError("db unavailable at boot")

    monkeypatch.setattr(JobService, "fail_orphaned_running_jobs", boom, raising=False)
    with TestClient(app) as client:
        assert client.get("/docs").status_code in (200, 404)
