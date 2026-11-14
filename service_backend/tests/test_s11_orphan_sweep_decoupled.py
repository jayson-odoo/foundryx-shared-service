"""Sprint-5/11 S1 - RED tests for the orphan sweep's OWN beat tick, decoupled
from the AutoCount scheduler (plan sec 2.6/2.7, D16; AC-11-56/AC-11-84).

Root cause of the 8-hour symptom (not the freeze itself, but why nobody
noticed): "the recovery machinery was queued behind the thing it recovers" -
outside app startup, the ONLY caller of ``fail_orphaned_running_jobs`` was
the AutoCount scheduler tick, itself a beat task on the very ``workflow``
queue the incident starved. D16: "the sweep must never share a queue with
the jobs it sweeps."

SCOPE NOTE (flagged for the plan owner, see the test report): the plan's own
slice table gates the FULL ``jobs.sweep_orphaned`` contract (running sweep
+ AC-11-50's new undispatched-pending sweep) at S2 (UAC column
"AC-11-50..57, 11-60"), not at S1's own row ("AC-11-80..88"). D16 is
introduced in S1's *narrative* (sec 2.6-2.7) and S1's own file list
(sec 3) already names "the jobs.sweep_orphaned beat entry" under
``worker.py``, so this file tests the RUNNING-only half a standalone beat
tick can deliver with ZERO new core logic (it wraps the ALREADY-EXISTING
``app.jobs.service.sweep_orphaned_jobs(db)``, used at startup today) -
independent of any per-module tick. It deliberately does NOT test
``fail_undispatched_pending_jobs`` (AC-11-50) or the undispatched half of
AC-11-56 - that stays S2's job. If the coder or reviewer decides the whole
beat entry should wait for S2 instead, this file's two tests are the ones to
defer; say so in the review rather than silently skip them.

CONTRACT this file pins:
- ``app/workflow_engine/worker.py``: a new Celery task named
  ``"jobs.sweep_orphaned"``, a ``beat_schedule`` entry for it at 300.0s (5
  minutes, per AC-11-56), routed onto the ``"workflow"`` queue (the D16
  invariant - explicitly NOT ``"jobs"``, the very queue it exists to keep
  clear). The task body opens its own ``app.database.SessionLocal()``
  (same convention as every other tick in this file) and calls the existing
  ``sweep_orphaned_jobs(db)``.
"""
from __future__ import annotations

from datetime import timedelta

from app.models.background_job import JOB_FAILED, JOB_NEEDS_REVIEW, JOB_RUNNING, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import RUN_FAILED, RUN_MODE_SKIPPED, AcSyncRun
from modules.autocount.scheduler import sweep_etl_tasks
from tests.test_autocount_scheduler import NOW, _jobs_for, _task
from tests.test_autocount_scheduler import _company as _sched_company
from tests.test_job_lease_orphan_sweep import _job, _open_run


def test_jobs_sweep_orphaned_beat_entry_runs_every_5_minutes_on_the_workflow_queue():
    from app.workflow_engine.worker import celery_app

    entries = [
        entry for entry in celery_app.conf.beat_schedule.values()
        if entry.get("task") == "jobs.sweep_orphaned"
    ]
    assert entries, (
        "beat_schedule has no jobs.sweep_orphaned entry (AC-11-56/D16) - "
        "S0 confirmed the only caller of the orphan sweep outside startup "
        "is the AutoCount scheduler tick, itself on the starved queue"
    )
    assert entries[0]["schedule"] == 300.0, "AC-11-56: every 5 minutes"

    route = celery_app.amqp.router.route({}, "jobs.sweep_orphaned")
    assert route["queue"].name == "workflow", (
        "D16: the sweep must never share a queue with the jobs it sweeps - "
        "routing this onto 'jobs' would starve it beside the very job it "
        "exists to recover from"
    )


def test_jobs_sweep_orphaned_task_fails_a_stale_running_job_and_leaves_needs_review_alone(
    session_factory, monkeypatch
):
    import app.database as app_database
    from app.workflow_engine.worker import celery_app

    # Task opens its OWN SessionLocal() (worker-process convention, mirrors
    # every other tick task in this file and the same seam
    # test_omnichannel_broadcasts_send.py uses for worker.broadcast_chunk).
    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    db = session_factory()
    company = _sched_company(db)
    stuck = _job(
        db, status=JOB_RUNNING, started_ago=timedelta(minutes=20), heartbeat_ago=None,
        now=NOW, company_id=company.id,
    )
    open_run = _open_run(db, stuck, started_at=NOW - timedelta(minutes=20), company_id=company.id)
    parked = _job(
        db, status=JOB_NEEDS_REVIEW, started_ago=timedelta(days=2), heartbeat_ago=None,
        now=NOW, company_id=company.id,
    )
    # Captured BEFORE db.close(): expire_on_commit=True (session_factory's
    # default) expires every attribute on the commits above, so reading
    # `.id` off these instances after the session that owns them is closed
    # raises DetachedInstanceError - a test-bug fix, not a contract change
    # (sprint-5/11 S1 coder round; see the handoff report).
    stuck_id, parked_id, open_run_id = stuck.id, parked.id, open_run.id
    db.close()

    task = celery_app.tasks["jobs.sweep_orphaned"]
    task()  # calling a Celery Task instance runs its body directly (no broker)

    fresh = session_factory()
    try:
        assert fresh.get(BackgroundJob, stuck_id).status == JOB_FAILED
        assert fresh.get(BackgroundJob, parked_id).status == JOB_NEEDS_REVIEW, (
            "a needs_review job must never be swept by the periodic tick "
            "either - the existing exclusion in fail_orphaned_running_jobs"
        )
        closed = fresh.get(AcSyncRun, open_run_id)
        assert closed.outcome == RUN_FAILED and closed.finished_at is not None
    finally:
        fresh.close()


def test_the_autocount_tick_proceeds_cleanly_once_the_periodic_sweep_already_cleaned_it(
    session_factory, monkeypatch
):
    """The scheduler tick must not need its OWN sweep-on-skip branch to fire
    once the standalone beat has already failed the stale job - it should
    simply see nothing in flight, exactly as it does for a task that was
    never stuck at all."""
    import app.database as app_database
    from app.workflow_engine.worker import celery_app

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    db = session_factory()
    company = _sched_company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    stuck = _job(
        db, status=JOB_RUNNING, started_ago=timedelta(minutes=20), heartbeat_ago=None,
        now=NOW, company_id=company.id,
    )
    _open_run(db, stuck, started_at=NOW - timedelta(minutes=20), company_id=company.id)
    # Captured BEFORE db.close() - see the sibling test's comment above for
    # why (DetachedInstanceError on a closed session's expired instances).
    company_id, stuck_id = company.id, stuck.id
    db.close()

    task = celery_app.tasks["jobs.sweep_orphaned"]
    task()

    db = session_factory()
    result = sweep_etl_tasks(db, now=NOW)
    db.expire_all()

    assert result == {"fired": 1, "skipped": 0, "failed": 0}
    jobs = _jobs_for(db, company_id, ENTITY_CUSTOMER)
    assert len(jobs) == 2 and any(j.id != stuck_id for j in jobs), (
        "a NEW job must have been enqueued for this tick"
    )
    skip_rows = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company_id, AcSyncRun.mode == RUN_MODE_SKIPPED)
        .count()
    )
    assert skip_rows == 0, "no skip row for this tick - the sweep already cleared the way"
    db.close()
