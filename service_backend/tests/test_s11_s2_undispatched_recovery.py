"""Sprint-5/11 S2 - RED tests for undispatched-pending-job recovery
(plan sec 2.4, D12/D13/D14; AC-11-50..57, AC-11-60).

Incident replayed (2026-09-21, production): a deploy restarted the worker
while a ``sales_order`` ``autocount_sync`` job was ``pending`` (``started_at``
NULL) - the Celery message itself was lost, so the job could NEVER start.
Every scheduler tick afterwards wrote a ``skipped`` run ("A run for this task
was still in progress") because the existing sweep
(``JobService.fail_orphaned_running_jobs``) is RUNNING-only by design: "a
PENDING one of any age is a backlogged queue" - which is exactly the
assumption this incident breaks. The job sat for 8+ hours until the owner
reset it by hand in SQL (job -> failed, ``ac_sync_run`` -> FAILED/Interrupted).

Owner ruling R6 (APPROVED as recommended, D12/D13): undispatched pending jobs
are FAILED, never re-dispatched. Re-dispatch looks attractive but collides
with ``run_job``'s RUNNING crash-resume branch - if the original (lost)
message is somehow delivered late AFTER a re-enqueue, two workers could
execute the same job and double-push. Failing costs one minute: the next
tick finds nothing in flight and enqueues a FRESH job.

CONTRACT this file pins (the coder implements to this; the plan's own naming
in sec 2.4/3 and AC-11-50 is authoritative where it conflicts with a guess
here):

- ``app/config.py``: ``background_job_undispatched_after_minutes: int = 60``
  with a ``@field_validator`` floor of 15 (mirrors
  ``background_job_orphan_after_minutes``'s existing floor-of-5 pattern
  exactly, just a different floor value per R6/AC-11-57).
- ``app/jobs/service.py``: ``JobService.UNDISPATCHED_ERROR`` (a class
  attribute string, mirroring ``JobService.ORPHANED_ERROR``), and
  ``JobService.fail_undispatched_pending_jobs(*, older_than=None, now=None,
  job_id=None) -> int`` - every job with ``status == 'pending'`` AND
  ``started_at IS NULL`` AND ``created_at < now - older_than`` (default
  ``settings.background_job_undispatched_after_minutes``) is FAILED with
  ``UNDISPATCHED_ERROR`` + ``finished_at``, then fans out through the SAME
  ``close_module_bookkeeping(db, job, now=)`` helper the orphan sweep and the
  soft-time-limit path already share (S1). UNLIKE the running sweep this is
  NOT restricted to ``heartbeats=True`` types (a lost message is
  type-agnostic - AC-11-50). Idempotent; returns the count; ``job_id``
  narrows to one job.
- ``app/workflow_engine/worker.py``: the existing ``jobs.sweep_orphaned``
  beat task (S1, wraps ``sweep_orphaned_jobs(db)`` only) is extended to ALSO
  run the new undispatched sweep, so every job type recovers without a
  scheduler in front of it (AC-11-56). Stays on the ``workflow`` queue (D16,
  already pinned by S1's own test file - not re-pinned here).
- ``modules/autocount/scheduler.py``: the AC-22-14 overlap guard's existing
  RUNNING-only branch gets a sibling branch for a stale PENDING/undispatched
  ``in_flight`` job - sweeps exactly that job via
  ``JobService(db).fail_undispatched_pending_jobs(older_than=..., now=now,
  job_id=in_flight.id)`` and, when it returns 1, proceeds with the tick
  exactly like the RUNNING branch (AC-11-53). A fresh pending job is
  untouched (AC-11-54, unchanged today).
- Never re-dispatched (D12/D13): no code path in the new sweep re-enqueues
  the swept job's Celery task.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService, close_module_bookkeeping
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    RUN_FAILED,
    RUN_MODE_MANUAL,
    RUN_MODE_SKIPPED,
    AcSyncRun,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.etl_service import EtlService, EtlStateError
from modules.autocount.sync import AUTOCOUNT_SYNC
from tests.test_autocount_scheduler import NOW, _jobs_for, _task
from tests.test_autocount_scheduler import _company as _sched_company
from tests.test_job_lease_orphan_sweep import INTERRUPTED, _open_run


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _pending_job(
    db,
    *,
    created_at: datetime,
    started_at: "datetime | None" = None,
    status: str = JOB_PENDING,
    job_type: str = AUTOCOUNT_SYNC,
    company_id: str = "co-1",
) -> BackgroundJob:
    """A job row with an EXPLICIT ``created_at`` (the column's
    ``server_default=func.now()`` only fires when the value is omitted, so
    passing it here lets the fixture's fixed clock (``NOW``, 2026-08-30)
    stand in for "how long ago" instead of real wall-clock time)."""
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=job_type, status=status,
        payload_json={"companyId": company_id, "entityType": ENTITY_CUSTOMER},
        created_at=created_at, started_at=started_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


UNDISPATCHED_TEXT_HINT = "never picked this job up"


# ═══════════════════════════════════════════════════════════════════════════
#  A - app/config.py: the setting + its floor (AC-11-57)
# ═══════════════════════════════════════════════════════════════════════════


def test_background_job_undispatched_after_minutes_default_is_150():
    """Review round 1 (owner-approved amendment 2026-09-21): 60 -> 150 so the
    window exceeds the default `background_job_soft_time_limit_seconds`
    (7200s = 120 min) - see the cross-field validator below - and a queued
    (not lost) message sitting behind a legitimately long `jobs.run` build on
    a busy `-c 2` worker is never mistaken for undispatched."""
    from app.config import Settings

    assert Settings().background_job_undispatched_after_minutes == 150


def test_background_job_undispatched_after_minutes_floor_is_15(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    # Isolate the per-field floor from the cross-field soft-time-limit check
    # (below) by giving the soft limit a small value too - the floor test is
    # about the 15-minute minimum by itself, not the cross-field relationship.
    monkeypatch.setenv("BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS", "60")

    monkeypatch.setenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", "14")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.delenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", raising=False)

    monkeypatch.setenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", "15")
    at_floor = Settings()
    assert at_floor.background_job_undispatched_after_minutes == 15
    monkeypatch.delenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", raising=False)
    monkeypatch.delenv("BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS", raising=False)


def test_background_job_undispatched_after_minutes_must_exceed_soft_time_limit(
    monkeypatch,
):
    """Review round 1 - the new cross-field validator (`model_validator(mode=
    "after")`): a window that does not outlive `jobs.run`'s own soft time
    limit would let the undispatched sweep fail a message that is merely
    queued behind a legitimate long build, not lost."""
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS", "7200")
    monkeypatch.setenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", "120")
    with pytest.raises(ValidationError, match="background_job_undispatched_after_minutes"):
        Settings()
    monkeypatch.delenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", raising=False)

    # Just over the boundary succeeds (120 min * 60 = 7200s is NOT > 7200s).
    monkeypatch.setenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", "121")
    ok = Settings()
    assert ok.background_job_undispatched_after_minutes == 121
    monkeypatch.delenv("BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES", raising=False)
    monkeypatch.delenv("BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS", raising=False)


# ═══════════════════════════════════════════════════════════════════════════
#  B - JobService.fail_undispatched_pending_jobs (AC-11-50, 11-51, 11-52)
# ═══════════════════════════════════════════════════════════════════════════


def test_job_service_declares_a_dedicated_undispatched_sentence():
    assert hasattr(JobService, "UNDISPATCHED_ERROR"), (
        "JobService.UNDISPATCHED_ERROR is missing - mirrors the existing "
        "JobService.ORPHANED_ERROR class-attribute pattern (AC-11-50)"
    )
    text = JobService.UNDISPATCHED_ERROR
    assert isinstance(text, str) and text
    assert text != JobService.ORPHANED_ERROR, (
        "a lost-message job and a dead-worker job are different incidents; "
        "they must not share one sentence"
    )
    assert not text.startswith("Job crashed"), (
        "this is a clean, expected recovery at a configured bound, not a crash"
    )
    assert UNDISPATCHED_TEXT_HINT in text.lower(), (
        f"got {text!r} - AC-11-50/11-59 both quote 'the worker never picked "
        "this job up' as the operator-facing wording; the Runs-list FE test "
        "(AC-11-59) and this sentence must agree"
    )


def test_fails_a_stale_undispatched_pending_job_and_closes_its_open_run(db):
    """The positive case (AC-11-50/11-52): PENDING, started_at NULL,
    created_at older than the window -> FAILED + finished_at + the open
    ac_sync_run closes through the SAME module hook the orphan sweep and the
    soft-time-limit path already share (S1's close_module_bookkeeping)."""
    stale = _pending_job(db, created_at=NOW - timedelta(minutes=90))
    open_run = _open_run(db, stale, started_at=NOW - timedelta(minutes=90))

    count = JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    )
    db.expire_all()

    assert count == 1
    fresh = db.get(BackgroundJob, stale.id)
    assert fresh.status == JOB_FAILED
    assert fresh.error == JobService.UNDISPATCHED_ERROR
    assert fresh.finished_at is not None

    closed = db.get(AcSyncRun, open_run.id)
    assert closed.outcome == RUN_FAILED
    assert closed.error == JobService.UNDISPATCHED_ERROR
    assert closed.finished_at is not None
    assert closed.duration_ms is not None and closed.duration_ms >= 0

    # Idempotent - a second sweep over the now-terminal job finds nothing.
    assert JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    ) == 0


def test_sweep_excludes_a_fresh_pending_job(db):
    fresh = _pending_job(db, created_at=NOW - timedelta(minutes=5))

    assert JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    ) == 0
    db.expire_all()
    assert db.get(BackgroundJob, fresh.id).status == JOB_PENDING


def test_sweep_excludes_a_stale_pending_job_that_already_started(db):
    """started_at IS NOT NULL means SOME worker did pick it up - that is the
    RUNNING sweep's business, never this one's (a job cannot be both
    'never dispatched' and 'started')."""
    started = _pending_job(
        db, created_at=NOW - timedelta(minutes=90), started_at=NOW - timedelta(minutes=85),
        status=JOB_PENDING,
    )

    assert JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    ) == 0
    db.expire_all()
    assert db.get(BackgroundJob, started.id).status == JOB_PENDING


@pytest.mark.parametrize(
    "status", [JOB_RUNNING, JOB_NEEDS_REVIEW, JOB_DONE, JOB_FAILED, JOB_ABORTED]
)
def test_sweep_never_touches_a_non_pending_status(db, status):
    """Explicit pin per the plan's own words: 'needs_review/done/failed/
    aborted never touched' - and RUNNING is the OTHER sweep's business."""
    other = _pending_job(
        db, created_at=NOW - timedelta(minutes=90), status=status,
        started_at=(NOW - timedelta(minutes=85)) if status == JOB_RUNNING else None,
    )

    assert JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    ) == 0
    db.expire_all()
    assert db.get(BackgroundJob, other.id).status == status


def test_job_id_filter_narrows_the_sweep_to_one_job(db):
    """Mirrors ``fail_orphaned_running_jobs``'s own ``job_id`` narrowing - the
    scheduler sweeps EXACTLY the stale in-flight job it would otherwise skip
    for, never every stale pending row tenant-wide in the same breath."""
    target = _pending_job(db, created_at=NOW - timedelta(minutes=90), company_id="co-1")
    other_stale = _pending_job(db, created_at=NOW - timedelta(minutes=120), company_id="co-2")

    count = JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW, job_id=target.id
    )
    db.expire_all()

    assert count == 1
    assert db.get(BackgroundJob, target.id).status == JOB_FAILED
    assert db.get(BackgroundJob, other_stale.id).status == JOB_PENDING, (
        "a job_id-scoped sweep must not sweep an unrelated stale row"
    )


def test_sweep_is_not_restricted_to_heartbeat_declaring_types(db):
    """AC-11-50: 'Unlike the running sweep it is NOT limited to
    heartbeats=True types - a lost message is type-agnostic.' Registers a
    type that explicitly does NOT declare heartbeats (mirrors the existing
    _FAKE_NO_HEARTBEAT control in test_job_lease_orphan_sweep.py) and proves
    it is still swept."""
    def _fake_handler(db, job):  # pragma: no cover - never run
        return None

    fake_type = "fake_no_heartbeat_undispatched"
    register_job_handler(JobHandlerDef(fake_type, _fake_handler, "Fake (no heartbeat)"))
    fake = _pending_job(db, created_at=NOW - timedelta(minutes=90), job_type=fake_type)

    count = JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    )
    db.expire_all()

    assert count == 1
    assert db.get(BackgroundJob, fake.id).status == JOB_FAILED


def test_never_re_dispatches_the_swept_jobs_celery_task(db, monkeypatch):
    """D12/D13: fail, never re-dispatch. Pins the seam directly - the sweep
    must never call the Celery entry point (jobs.run's task object) nor
    JobService.enqueue for the job it is failing."""
    import app.jobs.worker as jobs_worker_module

    delay_spy = Mock()
    apply_async_spy = Mock()
    enqueue_spy = Mock()
    monkeypatch.setattr(jobs_worker_module.run_job_task, "delay", delay_spy)
    monkeypatch.setattr(jobs_worker_module.run_job_task, "apply_async", apply_async_spy)
    monkeypatch.setattr(JobService, "enqueue", enqueue_spy)

    stale = _pending_job(db, created_at=NOW - timedelta(minutes=90))

    count = JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    )
    db.expire_all()

    assert count == 1
    assert db.get(BackgroundJob, stale.id).status == JOB_FAILED
    delay_spy.assert_not_called()
    apply_async_spy.assert_not_called()
    enqueue_spy.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
#  C - the core beat tick runs BOTH sweeps (AC-11-56)
# ═══════════════════════════════════════════════════════════════════════════


def test_the_jobs_sweep_orphaned_tick_also_fails_a_stale_undispatched_pending_job(
    session_factory, monkeypatch
):
    """S1 already pins that jobs.sweep_orphaned exists, runs every 5 minutes
    on the workflow queue, and fails a stale RUNNING job
    (test_s11_orphan_sweep_decoupled.py - not re-pinned here). This test
    pins the S2 half: the SAME tick must ALSO fail a stale UNDISPATCHED
    pending job of a DIFFERENT task, in one call - 'runs BOTH sweeps' per
    the plan (sec 2.4), not two separate ticks."""
    import app.database as app_database
    from app.workflow_engine.worker import celery_app

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    db = session_factory()
    company = _sched_company(db)
    # Older than the settings default (150 min, review round 1 amendment -
    # was 60/90 before the default moved so the window outlives
    # `background_job_soft_time_limit_seconds`).
    stale_pending = _pending_job(
        db, created_at=datetime.now(timezone.utc) - timedelta(minutes=200),
        company_id=company.id,
    )
    fresh_pending = _pending_job(
        db, created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        company_id=company.id,
    )
    stale_id, fresh_id = stale_pending.id, fresh_pending.id
    db.close()

    task = celery_app.tasks["jobs.sweep_orphaned"]
    task()

    fresh = session_factory()
    try:
        assert fresh.get(BackgroundJob, stale_id).status == JOB_FAILED, (
            "the periodic tick must recover a job type with no scheduler in "
            "front of it, not only the ones the AutoCount tick happens to "
            "cover (AC-11-56)"
        )
        assert fresh.get(BackgroundJob, fresh_id).status == JOB_PENDING
    finally:
        fresh.close()


# ═══════════════════════════════════════════════════════════════════════════
#  D - the AutoCount scheduler's overlap guard (AC-11-53, 11-54, 11-55)
# ═══════════════════════════════════════════════════════════════════════════


def test_scheduler_sweeps_a_stale_undispatched_job_and_the_tick_proceeds(session_factory):
    """AC-11-53, replaying the incident's own shape at the scheduler layer:
    a pending job aged past the window -> swept by exactly that job_id ->
    the tick proceeds as if nothing were in flight (a NEW job enqueued, no
    skip row for THIS tick) - one-for-one with the existing RUNNING branch."""
    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    # Older than the settings default (150 min, review round 1 amendment).
    stale = _pending_job(
        db, created_at=NOW - timedelta(minutes=200), company_id=company.id,
    )
    company_id, stale_id = company.id, stale.id

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    released = db.get(BackgroundJob, stale_id)
    assert released.status == JOB_FAILED
    assert released.error == JobService.UNDISPATCHED_ERROR

    jobs = _jobs_for(db, company_id, ENTITY_CUSTOMER)
    assert len(jobs) == 2 and any(j.id != stale_id for j in jobs), (
        "a NEW job must have been enqueued for this tick"
    )
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company_id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .count()
    )
    assert skip_rows == 0, "no skip row for this tick - the sweep already cleared the way"
    db.close()


def test_a_fresh_pending_job_one_minute_old_still_skips_the_tick(session_factory):
    """AC-11-54, explicit control: a job that is merely queued, not lost,
    must still cause the tick to skip exactly as today - a false-positive
    sweep here would double-run a task whose original message simply has not
    been picked up yet."""
    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    fresh = _pending_job(
        db, created_at=NOW - timedelta(minutes=1), company_id=company.id,
    )
    company_id, fresh_id = company.id, fresh.id

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 0, "skipped": 1, "failed": 0}
    assert db.get(BackgroundJob, fresh_id).status == JOB_PENDING
    assert len(_jobs_for(db, company_id, ENTITY_CUSTOMER)) == 1
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company_id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .all()
    )
    assert len(skip_rows) == 1
    assert "still in progress" in (skip_rows[0].skip_reason or "")
    db.close()


def test_manual_run_still_409s_against_a_fresh_undispatched_pending_job(db):
    """AC-11-55, control: the manual-run guard is UNCHANGED - it 409s on ANY
    in-flight job (pending or running), swept or not; it never itself
    performs the sweep."""
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    _pending_job(db, created_at=NOW - timedelta(minutes=1), company_id=company.id)

    with pytest.raises(EtlStateError) as excinfo:
        EtlService(db).run_task_now(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER)
    assert "still going" in str(excinfo.value).lower()


def test_manual_run_succeeds_once_the_stale_pending_job_has_been_swept(db):
    """AC-11-55, positive: once the ONLY in-flight job has been swept
    (terminal), the manual-run guard sees nothing in flight and the request
    succeeds - the human retry path this incident class relies on."""
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    _pending_job(db, created_at=NOW - timedelta(minutes=90), company_id=company.id)

    swept = JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=60), now=NOW
    )
    assert swept == 1

    result = EtlService(db).run_task_now(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER)
    assert result["job_id"]


# ═══════════════════════════════════════════════════════════════════════════
#  E - Runs-list visibility / incident replay (AC-11-60)
# ═══════════════════════════════════════════════════════════════════════════


def test_incident_replay_2026_09_21_recovers_cleanly_with_no_manual_sql(session_factory):
    """The 2026-09-21 production incident, end to end on the lane's own
    machinery (no manual SQL reset): a `sales_order`-shaped autocount_sync
    job stuck PENDING (started_at NULL) with a backdated created_at, its
    open ac_sync_run row present (the row the owner had to close by hand) -
    one scheduler tick recovers it: the job reads FAILED with the
    'worker never picked this job up' reason, its run row closes
    FAILED/finished, a fresh job is enqueued, and no skip row is written for
    this tick (AC-11-53/11-58/11-60)."""
    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    lost = _pending_job(
        db, created_at=NOW - timedelta(hours=8), company_id=company.id,
    )
    open_run = _open_run(db, lost, started_at=NOW - timedelta(hours=8), company_id=company.id)
    company_id, lost_id, open_run_id = company.id, lost.id, open_run.id

    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 1, "skipped": 0, "failed": 0}, (
        "before/after: the incident's every-tick 'skipped' loop must not "
        "reproduce once the sweep is in place"
    )

    recovered = db.get(BackgroundJob, lost_id)
    assert recovered.status == JOB_FAILED
    assert UNDISPATCHED_TEXT_HINT in (recovered.error or "").lower()
    assert recovered.finished_at is not None

    closed_run = db.get(AcSyncRun, open_run_id)
    assert closed_run.outcome == RUN_FAILED
    assert UNDISPATCHED_TEXT_HINT in (closed_run.error or "").lower()
    assert closed_run.finished_at is not None

    # A run with finishedAt set and outcome null is a SKIP (AC-11-58, the FE
    # badge rule); the recovered job's own run is FAILED (outcome set), and
    # no fresh SKIPPED row exists for this tick - "the four finished skip
    # rows from the incident" must not reproduce going forward.
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company_id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .count()
    )
    assert skip_rows == 0

    new_jobs = [j for j in _jobs_for(db, company_id, ENTITY_CUSTOMER) if j.id != lost_id]
    assert len(new_jobs) == 1, "the tick that recovered the incident must also fire a fresh run"
    db.close()
