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
    # conftest turns the startup sweep OFF for the suite; this test is about
    # what startup does when it is ON.
    monkeypatch.setattr(settings, "background_job_orphan_sweep_on_startup", True)
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


# ═══════════════════════════════════════════════════════════════════════════
#  Review round 1 (f2a9b5f3)
# ═══════════════════════════════════════════════════════════════════════════

from app.jobs.registry import JobHandlerDef, handler_for, register_job_handler  # noqa: E402
from app.models.background_job import JOB_PENDING  # noqa: E402
from modules.autocount.models import RUN_SUCCESS  # noqa: E402
from tests.test_autocount_bulk_load import _config_row  # noqa: E402


def _fake_handler(db, job):  # pragma: no cover - never run, registration only
    return None


_FAKE_NO_HEARTBEAT = JobHandlerDef("fake_no_heartbeat", _fake_handler, "Fake (no heartbeat)")


def _heartbeat_of(session_factory, job_id: str):
    s = session_factory()
    try:
        return s.execute(
            sa.text("SELECT heartbeat_at FROM background_jobs WHERE id = :i"), {"i": job_id}
        ).scalar()
    finally:
        s.close()


# ── B1: a stale PENDING in-flight job is not an orphan; the tick skips ──────


def test_a_stale_pending_in_flight_job_is_not_swept_and_the_tick_skips(session_factory):
    """Only RUNNING jobs can be orphaned (a pending job has no worker to
    lose). Today ``first_unfinished`` returns the pending job, the sweep
    releases nothing, and the tick fires anyway - a proven duplicate."""
    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    pending = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_PENDING,
        payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
        created_at=NOW - timedelta(minutes=20),
    )
    db.add(pending)
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 0, "skipped": 1, "failed": 0}
    assert db.get(BackgroundJob, pending.id).status == JOB_PENDING
    assert len(_jobs_for(db, company.id, ENTITY_CUSTOMER)) == 1
    db.close()


# ── B2: one heartbeat per push chunk ────────────────────────────────────────


def test_write_batch_calls_on_chunk_once_per_chunk():
    import httpx

    from modules.autocount.canonical.masters import CanonicalSupplier
    from modules.autocount.sinks_sorento import SorentoSink

    def respond(request: httpx.Request) -> httpx.Response:
        import json as _json

        records = _json.loads(request.content)["records"]
        return httpx.Response(200, json={
            "summary": {"total": len(records), "created": len(records), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": [
                {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "x"}
                for r in records
            ],
        })

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type="supplier",
        transport=httpx.MockTransport(respond), batch_size=3,
    )
    records = [
        CanonicalSupplier(source_ref=f"AED:{i}", source_doc_no=f"C{i}", code=f"C{i}", name="N", is_active=True)
        for i in range(7)
    ]
    beats: List[int] = []
    # Merged contract (fix/push-marks-per-chunk): ``on_chunk(chunk_records,
    # chunk_results_or_None, error_or_None)`` - still exactly once per chunk.
    results = sink.write_batch(
        records, request_id="t",
        on_chunk=lambda chunk, chunk_results, error: beats.append(len(chunk)),
    )
    assert len(results) == 7
    assert beats == [3, 3, 1]  # chunks of 3 / 3 / 1, one call each


def test_a_push_of_seven_rows_in_chunks_of_three_heartbeats_at_least_three_times(
    session_factory, monkeypatch, consumer
):
    """The push side of a run is the other multi-minute stretch: with the
    ingest batch size at 3 and 7 staged rows, the job must heartbeat once per
    chunk (observed as calls into ``JobService.heartbeat`` for THIS job), not
    once per push."""
    monkeypatch.setattr(settings, "autocount_page_size", 100, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 3, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(7))

    beats: List[str] = []
    original = JobService.heartbeat

    def counting(self, job_id, *, now=None):
        beats.append(str(job_id))
        return original(self, job_id, now=now)

    monkeypatch.setattr(JobService, "heartbeat", counting)

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE, job.error
    pushes = [r for r in consumer.requests if r["path"].endswith("/customers")]
    assert len(pushes) == 3, "7 rows at batch size 3 must be 3 ingest POSTs"
    # One page beat + at least one beat per chunk.
    assert beats.count(job.id) >= 4, f"heartbeats for the job: {beats.count(job.id)}"
    db.close()


# ── B3: only heartbeat-declaring job types are swept ────────────────────────


def test_autocount_sync_declares_heartbeats():
    assert handler_for(AUTOCOUNT_SYNC).heartbeats is True


def test_sweep_ignores_job_types_that_do_not_declare_heartbeats(db):
    """A type that never beats (storage migration, meetings STT) has no
    liveness signal to judge - reaping it by age would kill legitimate long
    runs. Only a ``JobHandlerDef(heartbeats=True)`` type is swept."""
    register_job_handler(_FAKE_NO_HEARTBEAT)
    assert getattr(_FAKE_NO_HEARTBEAT, "heartbeats", None) is False
    now = datetime.now(timezone.utc)
    fake = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=_FAKE_NO_HEARTBEAT.type, status=JOB_RUNNING,
        started_at=now - timedelta(hours=2),
    )
    db.add(fake)
    db.commit()
    ours = _job(db, status=JOB_RUNNING, started_ago=timedelta(hours=2), heartbeat_ago=None, now=now)

    assert JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD) == 1
    db.expire_all()
    assert db.get(BackgroundJob, fake.id).status == JOB_RUNNING
    assert db.get(BackgroundJob, ours.id).status == JOB_FAILED


# ── S4: the startup sweep is behind a settings flag ─────────────────────────


@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_startup_sweep_follows_the_settings_flag(monkeypatch, enabled):
    from fastapi.testclient import TestClient

    from app.main import app

    calls: List[dict] = []

    def recorder(self, *, older_than=None, now=None, job_id=None):
        calls.append({"older_than": older_than})
        return 0

    monkeypatch.setattr(JobService, "fail_orphaned_running_jobs", recorder)
    # The field may not exist on this HEAD: force it onto the live settings
    # object past pydantic's field check, restore afterwards.
    had = "background_job_orphan_sweep_on_startup" in settings.__dict__
    previous = settings.__dict__.get("background_job_orphan_sweep_on_startup")
    object.__setattr__(settings, "background_job_orphan_sweep_on_startup", enabled)
    try:
        with TestClient(app):
            pass
    finally:
        if had:
            object.__setattr__(settings, "background_job_orphan_sweep_on_startup", previous)
        else:
            settings.__dict__.pop("background_job_orphan_sweep_on_startup", None)

    assert bool(calls) is enabled, (
        f"startup sweep {'ran' if calls else 'did not run'} with the flag {enabled}"
    )


# ── S5: a heartbeat that stamps nothing means the job is gone - bail ────────


def test_a_run_whose_job_was_failed_elsewhere_stops_before_the_next_page(
    session_factory, monkeypatch, consumer
):
    """Mirror of the abort test: the job is flipped to ``failed`` on another
    session while page 2's SELECT runs (an orphan sweep that judged an
    unusually slow page as dead). The loop must stop before page 3 and must
    not overwrite the terminal status with ``done``."""
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(6))  # 3 pages of 2

    calls = {"n": 0}
    other = session_factory()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        calls["n"] += 1
        if calls["n"] == 2:
            job_id = other.execute(
                sa.text(
                    "SELECT id FROM background_jobs WHERE tenant_id = :t "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": DEFAULT_TENANT_ID},
            ).scalar()
            other.execute(
                sa.text("UPDATE background_jobs SET status = :s, error = :e WHERE id = :i"),
                {"s": JOB_FAILED, "e": INTERRUPTED, "i": job_id},
            )
            other.commit()

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        db = session_factory()
        job = _run(db, company_id, RUN_MODE_MANUAL)
        run = _run_row(db, company_id, job.id)

        assert job.status == JOB_FAILED, "the terminal status set elsewhere must survive"
        assert job.error == INTERRUPTED
        assert run.outcome != RUN_SUCCESS
        assert run.rows_scanned <= 4, "page 3 must never be read"
        assert calls["n"] <= 2
        db.close()
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
        other.close()


# ── S6: a raising module hook never loses the job's failed write ────────────


def test_a_raising_module_hook_runs_inside_a_savepoint_and_the_job_still_fails(db, monkeypatch):
    import app.jobs.service as job_service_module

    seen = {"nested": None}

    def raising_hook(session, job):
        seen["nested"] = session.in_nested_transaction()
        raise RuntimeError("module bookkeeping exploded")

    monkeypatch.setattr(
        job_service_module, "_orphan_hooks", lambda: [("broken_module", raising_hook)]
    )
    now = datetime.now(timezone.utc)
    stale = _job(db, status=JOB_RUNNING, started_ago=timedelta(hours=1), heartbeat_ago=None, now=now)

    assert JobService(db).fail_orphaned_running_jobs(older_than=THRESHOLD) == 1
    db.expire_all()
    assert db.get(BackgroundJob, stale.id).status == JOB_FAILED
    assert seen["nested"] is True, (
        "the hook must run inside a SAVEPOINT so a failing statement in it "
        "cannot poison the sweep's transaction on Postgres"
    )


# ── S7: on_job_orphaned is tenant-scoped ────────────────────────────────────


def test_on_job_orphaned_ignores_a_run_row_of_another_tenant_with_the_same_job_id(db):
    from modules.autocount.bootstrap import on_job_orphaned

    now = datetime.now(timezone.utc)
    job = _job(db, status=JOB_FAILED, started_ago=timedelta(hours=1), heartbeat_ago=None, now=now)
    job.error = INTERRUPTED
    db.commit()
    mine = _open_run(db, job, started_at=now - timedelta(hours=1))
    theirs = AcSyncRun(
        tenant_id="tenant-other-orphan", company_id="co-x", entity_type=ENTITY_CUSTOMER,
        job_id=job.id, mode=RUN_MODE_INCREMENTAL, started_at=now - timedelta(hours=1),
    )
    db.add(theirs)
    db.commit()

    on_job_orphaned(db, job)
    db.commit()
    db.expire_all()

    assert db.get(AcSyncRun, mine.id).outcome == RUN_FAILED
    other = db.get(AcSyncRun, theirs.id)
    assert other.finished_at is None and other.outcome is None


# ── S8: the first beat lands BEFORE page-1 extraction ───────────────────────


def test_the_first_heartbeat_lands_before_the_first_page_is_read(session_factory, monkeypatch, consumer):
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(2))

    seen: List[Optional[str]] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        job_id = None
        s = session_factory()
        try:
            row = s.execute(
                sa.text(
                    "SELECT id, heartbeat_at FROM background_jobs WHERE status = :s "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": JOB_RUNNING},
            ).first()
        finally:
            s.close()
        seen.append(row[1] if row else None)

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        db = session_factory()
        job = _run(db, company_id, RUN_MODE_MANUAL)
        assert job.status == JOB_DONE, job.error
        assert seen, "the page SELECT was never observed"
        assert seen[0] is not None, "no heartbeat before the first page's SELECT"
        db.close()
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)


# ── S9: the non-paged sql_db path beats before its push ─────────────────────


def test_a_non_paged_sql_db_run_heartbeats_before_its_push(session_factory, monkeypatch, consumer):
    """A ``sql_db`` task with NO watermark column takes the older single-fetch
    path; it must still beat at least once before the push so a long extract
    plus push is never judged dead by the sweep."""
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(3))
    db = session_factory()
    config = _config_row(db, company_id)
    config.source_config = {**config.source_config, "watermarkColumn": None}
    db.commit()

    observed: List[Optional[str]] = []
    original_upsert = consumer._upsert

    def observing_upsert(body):
        s = session_factory()
        try:
            observed.append(
                s.execute(
                    sa.text(
                        "SELECT heartbeat_at FROM background_jobs WHERE status = :s "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"s": JOB_RUNNING},
                ).scalar()
            )
        finally:
            s.close()
        return original_upsert(body)

    consumer._upsert = observing_upsert

    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE, job.error
    assert observed, "no push happened"
    assert observed[0] is not None, "no heartbeat before the first push"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Review round 2 (575b84c1): S13 / S14
# ═══════════════════════════════════════════════════════════════════════════

from modules.autocount.sql_source.source import CURSOR_MARK  # noqa: E402
from tests.test_autocount_bulk_load import _watermark_row  # noqa: E402

SENTINEL_SUCCESS_AT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _fail_running_job_elsewhere(session_factory) -> None:
    other = session_factory()
    try:
        job_id = other.execute(
            sa.text(
                "SELECT id FROM background_jobs WHERE status = :s "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"s": JOB_RUNNING},
        ).scalar()
        other.execute(
            sa.text("UPDATE background_jobs SET status = :s, error = :e WHERE id = :i"),
            {"s": JOB_FAILED, "e": INTERRUPTED, "i": job_id},
        )
        other.commit()
    finally:
        other.close()


# ── S14: a batch-level sink fault never discards the committed advance ──────


def test_a_batch_level_sink_error_on_push_leaves_the_watermark_advance_committed(
    session_factory, monkeypatch, consumer
):
    """S10 direction pinned: the cursor/high-water mark is committed BEFORE
    the push, so a consumer that answers a batch-level error (or dies) can
    never make the next run re-extract the same window; the staged rows are
    the retry unit."""
    import httpx

    monkeypatch.setattr(settings, "autocount_page_size", 100, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    from modules.autocount.models import AcWatermark as _AcWatermark

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(5))

    # Eager mode runs the handler on THIS session, so the run's own session
    # is inspectable from inside the push: when the first POST goes out, the
    # watermark advance must already be COMMITTED - i.e. not sitting in the
    # session's pending (dirty) state where a process death mid-push would
    # lose it. (A fresh-session read-back cannot tell on the StaticPool rig:
    # every session shares one connection and sees uncommitted state.)
    db = session_factory()
    observed = {"watermark_pending_at_first_push": None}

    def failing_upsert(body):
        if observed["watermark_pending_at_first_push"] is None:
            observed["watermark_pending_at_first_push"] = any(
                isinstance(obj, _AcWatermark) for obj in list(db.dirty) + list(db.new)
            )
        return httpx.Response(500, json={"message": "Internal server error"})

    consumer._upsert = failing_upsert
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status != JOB_RUNNING
    db.close()

    assert observed["watermark_pending_at_first_push"] is not None, "the push never happened"
    assert observed["watermark_pending_at_first_push"] is False, (
        "the watermark advance was still uncommitted on the run's session when "
        "the first push went out - a crash mid-push would re-extract the window"
    )

    fresh = session_factory()
    try:
        watermark = _watermark_row(fresh, company_id)
        assert watermark.last_modified_at is not None, "the high-water mark was not committed"
        assert (watermark.cursor_json or {}).get(CURSOR_MARK) is not None
        assert (
            fresh.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == company_id, AcStagedRecord.status == STAGED)
            .count()
            == 5
        ), "the staged rows are the retry unit and must survive the sink fault"
    finally:
        fresh.close()


# ── S13: a lost lease mid-push must not read as a healthy sync ──────────────


def test_a_lost_lease_mid_push_advances_the_retry_position_but_not_the_health_fields(
    session_factory, monkeypatch, consumer
):
    """The pre-push commit may carry ONLY the retry position (cursor /
    ``last_modified_at``). ``last_success_at``, ``consecutive_failures`` and
    ``last_error`` are the stale-sync signal an operator reads - they may
    only move once the push has actually resolved. A job swept as an orphan
    (failed elsewhere) between two push chunks must leave them exactly as
    they were."""
    monkeypatch.setattr(settings, "autocount_page_size", 100, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 3, raising=False)

    company_id, _sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(2))

    db = session_factory()
    first = _run(db, company_id, RUN_MODE_MANUAL)
    assert first.status == JOB_DONE, first.error
    watermark = _watermark_row(db, company_id)
    mark_before = watermark.last_modified_at
    assert mark_before is not None
    # Sentinel health values - anything the run writes here is detectable.
    watermark.last_success_at = SENTINEL_SUCCESS_AT
    watermark.consecutive_failures = 3
    watermark.last_error = "sentinel: earlier failure"
    db.commit()
    db.close()

    # Seven NEW rows (distinct keys, later marks): 3 chunks of 3 / 3 / 1.
    _insert_rows(
        engine,
        [(f"300-C{i:04d}", f"Late {i}", f"l{i}@x.com", f"2026-08-01 01:{i:02d}:00") for i in range(7)],
    )

    original_upsert = consumer._upsert
    pushes = {"n": 0}

    def flipping_upsert(body):
        pushes["n"] += 1
        if pushes["n"] == 1:
            # The orphan sweep (another process) fails the job while the
            # first chunk is on the wire.
            _fail_running_job_elsewhere(session_factory)
        return original_upsert(body)

    consumer._upsert = flipping_upsert

    db = session_factory()
    second = _run(db, company_id, RUN_MODE_MANUAL)
    assert second.status == JOB_FAILED, "the sweep's verdict must stand"
    assert second.error == INTERRUPTED
    assert pushes["n"] < 3, "the push must stop at the chunk boundary after the lost lease"
    db.close()

    fresh = session_factory()
    try:
        after = _watermark_row(fresh, company_id)
        assert after.last_modified_at > mark_before, "the retry position must have advanced"
        assert after.last_success_at == SENTINEL_SUCCESS_AT
        assert after.consecutive_failures == 3
        assert after.last_error == "sentinel: earlier failure"
    finally:
        fresh.close()
