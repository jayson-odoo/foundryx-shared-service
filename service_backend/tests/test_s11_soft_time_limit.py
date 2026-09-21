"""Sprint-5/11 S1 - RED tests for cooperative SoftTimeLimitExceeded handling
in ``run_job`` (AC-11-83).

Today (S0 baseline confirmed) ``run_job``'s handler dispatch is guarded by a
single generic ``except Exception as exc`` that marks the job ``failed`` with
``error=f"Job crashed: {exc}"`` and returns - it does NOT run any module
close hook. ``celery.exceptions.SoftTimeLimitExceeded`` IS an ``Exception``
subclass (verified: ``billiard.exceptions.SoftTimeLimitExceeded -> Exception
-> BaseException``), so it is already silently swallowed by that generic
branch today - but with the WRONG, non-cooperative shape: no dedicated
sentence, and critically no module bookkeeping closed (the ``ac_sync_run``
row stays open forever, exactly like the object-level orphan case this whole
plan exists to fix).

CONTRACT this file pins:
- ``app/jobs/service.py`` gains ``JobService.SOFT_TIME_LIMIT_ERROR`` (a
  class attribute, mirroring the existing ``JobService.ORPHANED_ERROR``
  pattern exactly), and a shared helper ``close_module_bookkeeping(db, job,
  *, now=None)`` - the SAME hook fan-out ``fail_orphaned_running_jobs``
  already performs per-hook-SAVEPOINT, extracted so the orphan sweep, the
  (S2) undispatched sweep and this time-limit path can never drift apart
  (plan sec 2.6, "That hook fan-out moves out of fail_orphaned_running_jobs
  into one helper shared by all three closers").
- ``run_job`` catches ``celery.exceptions.SoftTimeLimitExceeded`` BEFORE the
  generic ``except Exception``, stamps ``JobService.SOFT_TIME_LIMIT_ERROR``
  (not the generic "Job crashed: ..." text), calls
  ``close_module_bookkeeping(db, job)``, and does not re-raise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.jobs.service import JobService, run_job
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_FAILED, JOB_RUNNING, BackgroundJob
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import RUN_FAILED, RUN_MODE_MANUAL, AcSyncRun
from modules.autocount.sync import AUTOCOUNT_SYNC


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _raising_handler(db, job):
    """Stands in for a handler whose work is cut off by Celery's soft time
    limit signal - the shape ``run_job`` must survive cooperatively."""
    raise SoftTimeLimitExceeded()  # deliberately no message: proves the
    # error text on the job comes from OUR dedicated sentence, never from
    # str(exc) (which would be empty here) via the old generic branch.


def _running_job(db, *, job_type: str = AUTOCOUNT_SYNC) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=job_type, status=JOB_RUNNING,
        payload_json={"companyId": "co-1", "entityType": ENTITY_CUSTOMER},
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _open_run(db, job: BackgroundJob) -> AcSyncRun:
    run = AcSyncRun(
        tenant_id=DEFAULT_TENANT_ID, company_id="co-1", entity_type=ENTITY_CUSTOMER,
        job_id=job.id, mode=RUN_MODE_MANUAL,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_job_service_declares_a_dedicated_soft_time_limit_sentence():
    assert hasattr(JobService, "SOFT_TIME_LIMIT_ERROR"), (
        "JobService.SOFT_TIME_LIMIT_ERROR is missing - mirrors the existing "
        "JobService.ORPHANED_ERROR class-attribute pattern"
    )
    assert isinstance(JobService.SOFT_TIME_LIMIT_ERROR, str)
    assert JobService.SOFT_TIME_LIMIT_ERROR != ""
    # Must name the limit, and must NOT be the generic crash phrasing - the
    # whole point of AC-11-83 is that this path is cooperative, not a crash.
    assert "time limit" in JobService.SOFT_TIME_LIMIT_ERROR.lower()
    assert not JobService.SOFT_TIME_LIMIT_ERROR.startswith("Job crashed")


def test_run_job_fails_cooperatively_on_a_soft_time_limit_and_never_reraises(
    db, monkeypatch
):
    import app.jobs.service as job_service_module

    monkeypatch.setattr(job_service_module, "handler_for", lambda t: _StubDef())
    job = _running_job(db)

    # Must not raise - a worker that let this propagate would crash the
    # ForkPoolWorker instead of failing the job cleanly.
    run_job(db, job.id)

    db.expire_all()
    fresh = db.get(BackgroundJob, job.id)
    assert fresh.status == JOB_FAILED
    assert fresh.error == JobService.SOFT_TIME_LIMIT_ERROR, (
        f"got {fresh.error!r} - the generic 'Job crashed: ' branch must not "
        "be the one that catches this exception type"
    )
    assert fresh.finished_at is not None


def test_run_job_closes_the_open_ac_sync_run_on_a_soft_time_limit(db, monkeypatch):
    """AC-11-83's whole reason to exist: without the module hook fan-out,
    the Runs list would show this job's run forever 'in progress', exactly
    the 2026-09-21 incident symptom this plan is fixing."""
    import app.jobs.service as job_service_module

    monkeypatch.setattr(job_service_module, "handler_for", lambda t: _StubDef())
    job = _running_job(db)
    run = _open_run(db, job)

    run_job(db, job.id)

    db.expire_all()
    closed = db.get(AcSyncRun, run.id)
    assert closed.outcome == RUN_FAILED, "the ac_sync_run row was never closed"
    assert closed.error == JobService.SOFT_TIME_LIMIT_ERROR
    assert closed.finished_at is not None
    assert closed.duration_ms is not None and closed.duration_ms >= 0


def test_close_module_bookkeeping_is_a_shared_helper_reused_by_the_orphan_sweep(db):
    """Pins the D-sec-2.6 refactor itself: one helper, three call sites
    (orphan sweep, S2's undispatched sweep, this time-limit path) - not
    three copies of the same hook fan-out drifting apart."""
    from app.jobs.service import close_module_bookkeeping

    job = _running_job(db)
    run = _open_run(db, job)
    job.status = JOB_FAILED
    job.error = JobService.SOFT_TIME_LIMIT_ERROR
    job.finished_at = datetime.now(timezone.utc)
    db.commit()

    close_module_bookkeeping(db, job)
    db.commit()
    db.expire_all()

    closed = db.get(AcSyncRun, run.id)
    assert closed.outcome == RUN_FAILED
    assert closed.finished_at is not None


def _plain_raising_handler(db, job):
    """A handler that crashes with an ordinary exception - the S3 review-round-1
    gap: the generic `except Exception` branch in `run_job` failed the job but
    never closed module bookkeeping, leaving an open `ac_sync_run` row exactly
    like the soft-time-limit and orphan-sweep cases this plan already fixes."""
    raise RuntimeError("boom")


class _PlainRaisingDef:
    handler = staticmethod(_plain_raising_handler)


def test_run_job_closes_the_open_ac_sync_run_on_a_plain_handler_crash(db, monkeypatch):
    """S3 (review round 1) - a plain (non-SoftTimeLimitExceeded) crash must
    close the same module bookkeeping the soft-limit branch already does."""
    import app.jobs.service as job_service_module

    monkeypatch.setattr(job_service_module, "handler_for", lambda t: _PlainRaisingDef())
    job = _running_job(db)
    run = _open_run(db, job)

    run_job(db, job.id)

    db.expire_all()
    fresh = db.get(BackgroundJob, job.id)
    assert fresh.status == JOB_FAILED
    assert fresh.error == "Job crashed: boom"

    closed = db.get(AcSyncRun, run.id)
    assert closed.outcome == RUN_FAILED, "the ac_sync_run row was never closed"
    assert closed.finished_at is not None
    assert closed.duration_ms is not None and closed.duration_ms >= 0


class _StubDef:
    """Minimal stand-in for a ``JobHandlerDef`` - ``run_job`` only reads
    ``.handler`` off whatever ``handler_for`` returns."""

    handler = staticmethod(_raising_handler)
