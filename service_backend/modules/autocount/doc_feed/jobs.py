"""Doc-feed background-job handlers (D15) - ``autocount_doc_feed_run``
(poll / sweep, payload ``{feedId, kind}``) and
``autocount_doc_feed_backfill`` (payload ``{backfillId}``).

    !!  The Celery worker boots NO FastAPI lifespan.  !!

A worker only sees handlers whose MODULE was imported, so
``app/workflow_engine/worker.py`` must import ``modules.autocount.sync``
(which imports this module at its own tail) - forgetting that import leaves
every doc-feed job Pending forever with no error (the same footgun
``sync.py``'s own docstring names for ``autocount_sync``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.crash_text import crash_text
from app.jobs.service import JobService
from app.models.background_job import JOB_DONE, JOB_FAILED, BackgroundJob

from ..models import (
    DOC_FEED_BACKFILL_RUNNING,
    DOC_FEED_BACKFILL_STOPPED,
    DOC_FEED_BACKFILL_STOPPING,
    DOC_FEED_MODE_OFF,
    DOC_FEED_MODE_PUSH,
    AcDocFeedBackfill,
)
from ..repositories.doc_feed_repository import DocFeedBackfillRepository, DocFeedRepository
from .constants import (
    DOC_FEED_BACKFILL_JOB_TYPE,
    DOC_FEED_RUN_JOB_TYPE,
    RUN_KIND_POLL,
    RUN_KIND_SWEEP,
)
from .runner import run_backfill, run_poll, run_sweep, segment_continues

logger = logging.getLogger("foundryx.autocount")


def _split_transport(transport: Any):
    """S10 (review round 1) - test-only seam translation. The router's ONE
    ``get_http_transport`` override arrives here as a single object, but
    ``HttpApiClient`` (the vendor side) wants a FULL ``httpx.Client`` while
    ``SorentoSink`` (the CRM side) wants a bare ``httpx.BaseTransport`` - so
    the SAME override must serve both shapes. Production always leaves
    ``transport=None`` (both sides build their own real client, unaffected).
    A raw transport (e.g. ``httpx.MockTransport``) is wrapped into a
    ``Client`` for the vendor side and used AS-IS for the sink side; an
    already-built ``Client`` (the vendor-only shape earlier tests pass) is
    used as-is for the vendor side and unwrapped back to its own transport
    for the sink side - either way the CRM probe (``fetch_contract_detail``,
    S1) and the vendor reads share the ONE route-level stub a test can
    override in one place."""
    if transport is None:
        return None, None
    if isinstance(transport, httpx.Client):
        return transport, transport._transport  # noqa: SLF001 - test-only unwrap
    return httpx.Client(transport=transport), transport


def run_doc_feed_job(db: Session, job: BackgroundJob, *, transport: Any = None) -> None:
    """``autocount_doc_feed_run`` - poll / sweep, one feed. Dry-run-
    ness is read from the feed's OWN mode at run start (D15) - never
    stored on the job payload, so an operator's mode change between claim
    and dispatch is honoured, not stale."""
    service = JobService(db)
    payload = dict(job.payload_json or {})
    feed_id = str(payload.get("feedId") or "")
    kind = str(payload.get("kind") or "")
    feed_row = DocFeedRepository(db).get_by_id(job.tenant_id, feed_id)
    if feed_row is None:
        service.finish(job, status=JOB_FAILED, error="The feed no longer exists.")
        return
    if feed_row.mode == DOC_FEED_MODE_OFF:
        # N2 (review round 1) - a job claimed while the feed was on, then
        # switched Off before this dispatch actually ran, must be a no-op:
        # never a dry run the operator never asked for.
        service.finish(job, status=JOB_DONE)
        return
    dry_run = feed_row.mode != DOC_FEED_MODE_PUSH
    now = datetime.now(timezone.utc)
    vendor_transport, sink_transport = _split_transport(transport)
    try:
        if kind == RUN_KIND_POLL:
            run_poll(
                db, feed_row, dry_run=dry_run, now=now, job_id=job.id,
                vendor_transport=vendor_transport, sink_transport=sink_transport,
            )
        elif kind == RUN_KIND_SWEEP:
            run_sweep(
                db, feed_row, dry_run=dry_run, now=now, job_id=job.id,
                vendor_transport=vendor_transport, sink_transport=sink_transport,
            )
        else:
            service.finish(job, status=JOB_FAILED, error=f"Unknown doc-feed run kind '{kind}'.")
            return
    except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
        logger.exception("doc-feed run job %s crashed", job.id)
        db.rollback()
        service.finish(job, status=JOB_FAILED, error=crash_text(exc))
        return
    service.finish(job, status=JOB_DONE)


def run_doc_feed_backfill_job(db: Session, job: BackgroundJob, *, transport: Any = None) -> None:
    """``autocount_doc_feed_backfill`` - one day-loop SEGMENT (D13).

    SS-BACKFILL-CHUNKED: a segment reads for at most
    ``autocount_doc_feed_backfill_segment_seconds`` then queues the next
    segment (``_queue_next_segment``), so a multi-year backfill never meets
    the job's own time limit. However this job ends - done, time limit,
    crash - the backfill row is never left ``running``/``stopping`` without
    a worker: a stopped row is resumable from the UI."""
    service = JobService(db)
    payload = dict(job.payload_json or {})
    backfill_id = str(payload.get("backfillId") or "")
    backfill = DocFeedBackfillRepository(db).get(job.tenant_id, backfill_id)
    if backfill is None:
        service.finish(job, status=JOB_FAILED, error="The backfill no longer exists.")
        return
    if backfill.job_id and backfill.job_id != job.id:
        # Kill-proof fence: this is a stale segment (the backfill was
        # reaped and resumed under a newer job) - never read a day.
        service.finish(job, status=JOB_DONE)
        return
    now = datetime.now(timezone.utc)
    vendor_transport, sink_transport = _split_transport(transport)
    try:
        run_backfill(db, backfill, now=now, vendor_transport=vendor_transport, sink_transport=sink_transport)
    except SoftTimeLimitExceeded:
        logger.error("doc-feed backfill job %s hit its time limit", job.id)
        db.rollback()
        _close_backfill_stopped(db, job, backfill_id, code=BACKFILL_TIME_LIMIT_CODE,
                                message=BACKFILL_TIME_LIMIT_MESSAGE)
        service.finish(job, status=JOB_FAILED, error=JobService.SOFT_TIME_LIMIT_ERROR)
        return
    except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
        logger.exception("doc-feed backfill job %s crashed", job.id)
        db.rollback()
        error = crash_text(exc)
        _close_backfill_stopped(db, job, backfill_id, code=BACKFILL_CRASHED_CODE, message=error)
        service.finish(job, status=JOB_FAILED, error=error)
        return
    db.refresh(backfill)
    if not segment_continues(backfill):
        service.finish(job, status=JOB_DONE)
        return
    next_job = _queue_next_segment(db, backfill, job)
    service.finish(job, status=JOB_DONE)
    _dispatch_segment(db, next_job, transport=transport)


BACKFILL_TIME_LIMIT_CODE = "TIME_LIMIT"
BACKFILL_TIME_LIMIT_MESSAGE = (
    "Stopped: this backfill ran past the job time limit. Resume continues from the next day."
)
BACKFILL_CRASHED_CODE = "CRASHED"


def _close_backfill_stopped(db: Session, job: BackgroundJob, backfill_id: str, *, code: str, message: str) -> None:
    """End a backfill whose job is ending abnormally as ``stopped`` (resumable)
    with the error recorded. Only an in-flight row owned by THIS job flips: a
    ``done``/``stopped`` row, or one a newer job owns, stays as it is. Never
    raises (the caller still has to finish the job row)."""
    try:
        backfill = DocFeedBackfillRepository(db).get(job.tenant_id, backfill_id)
        if backfill is None:
            return
        db.refresh(backfill)
        if backfill.job_id and backfill.job_id != job.id:
            return
        if backfill.status in (DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING):
            backfill.status = DOC_FEED_BACKFILL_STOPPED
            backfill.error = (message or "")[:4000]
            backfill.error_code = code
            db.commit()
    except Exception:  # noqa: BLE001 - the reaper is the backstop
        logger.exception("doc-feed backfill %s could not be closed as stopped", backfill_id)
        db.rollback()


def _queue_next_segment(db: Session, backfill: AcDocFeedBackfill, job: BackgroundJob) -> BackgroundJob:
    """Create the next segment's job and point the backfill at it in ONE
    commit, before this job finishes: the row is never `running` under a
    finished job for longer than this call."""
    next_job = JobService(db).create(
        type=DOC_FEED_BACKFILL_JOB_TYPE, tenant_id=job.tenant_id,
        actor_user_id=getattr(job, "actor_user_id", None),
        payload={"backfillId": backfill.id},
    )
    backfill.job_id = next_job.id
    db.commit()
    return next_job


def _dispatch_segment(db: Session, next_job: BackgroundJob, *, transport: Any) -> None:
    """The same ONE-dispatch-path rule ``DocFeedService._dispatch`` keeps: a
    test's transport override (eager only) runs the next segment inline with
    it; everything else goes through ``JobService.enqueue`` (Celery in prod,
    inline in eager dev). A failed enqueue leaves a pending job the
    undispatched sweep fails, after which the reaper stops the row."""
    from app.config import settings

    if settings.celery_task_always_eager and transport is not None:
        jobs = JobService(db)
        if not jobs.claim(next_job.id):
            return
        db.refresh(next_job)
        try:
            run_doc_feed_backfill_job(db, next_job, transport=transport)
        except Exception as exc:  # noqa: BLE001 - mirrors _run_eager_with_transport
            db.rollback()
            jobs.finish(next_job, status=JOB_FAILED, error=crash_text(exc))
        return
    try:
        JobService(db).enqueue(next_job.id)
    except Exception:  # noqa: BLE001 - the sweeps + reaper recover it
        logger.exception("doc-feed backfill: next segment %s could not be queued", next_job.id)


_RUN_HANDLER_DEF = JobHandlerDef(
    DOC_FEED_RUN_JOB_TYPE, run_doc_feed_job, "AutoCount document feed run",
    heartbeats=True, read_permission="autocount.sync.read",
)
_BACKFILL_HANDLER_DEF = JobHandlerDef(
    DOC_FEED_BACKFILL_JOB_TYPE, run_doc_feed_backfill_job, "AutoCount document feed backfill",
    heartbeats=True, read_permission="autocount.companies.read",
)


def register_doc_feed_job_handlers() -> None:
    register_job_handler(_RUN_HANDLER_DEF)
    register_job_handler(_BACKFILL_HANDLER_DEF)
