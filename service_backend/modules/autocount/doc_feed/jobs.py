"""Doc-feed background-job handlers (D15) - ``autocount_doc_feed_run``
(poll / sweep / branch, payload ``{feedId, kind}``) and
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

from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_DONE, JOB_FAILED, BackgroundJob

from ..models import DOC_FEED_MODE_PUSH
from ..repositories.doc_feed_repository import DocFeedBackfillRepository, DocFeedRepository
from .constants import (
    DOC_FEED_BACKFILL_JOB_TYPE,
    DOC_FEED_RUN_JOB_TYPE,
    RUN_KIND_BRANCH,
    RUN_KIND_POLL,
    RUN_KIND_SWEEP,
)
from .runner import run_backfill, run_branch_pull, run_poll, run_sweep

logger = logging.getLogger("foundryx.autocount")


def run_doc_feed_job(db: Session, job: BackgroundJob, *, transport: Any = None) -> None:
    """``autocount_doc_feed_run`` - poll / sweep / branch, one feed. Dry-run-
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
    dry_run = feed_row.mode != DOC_FEED_MODE_PUSH
    now = datetime.now(timezone.utc)
    try:
        if kind == RUN_KIND_POLL:
            run_poll(db, feed_row, dry_run=dry_run, now=now, vendor_transport=transport)
        elif kind == RUN_KIND_SWEEP:
            run_sweep(db, feed_row, dry_run=dry_run, now=now, vendor_transport=transport)
        elif kind == RUN_KIND_BRANCH:
            run_branch_pull(db, feed_row, dry_run=dry_run, now=now, vendor_transport=transport)
        else:
            service.finish(job, status=JOB_FAILED, error=f"Unknown doc-feed run kind '{kind}'.")
            return
    except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
        logger.exception("doc-feed run job %s crashed", job.id)
        db.rollback()
        service.finish(job, status=JOB_FAILED, error=f"Job crashed: {exc}")
        return
    service.finish(job, status=JOB_DONE)


def run_doc_feed_backfill_job(db: Session, job: BackgroundJob, *, transport: Any = None) -> None:
    """``autocount_doc_feed_backfill`` - one day-loop segment (D13)."""
    service = JobService(db)
    payload = dict(job.payload_json or {})
    backfill_id = str(payload.get("backfillId") or "")
    backfill = DocFeedBackfillRepository(db).get(job.tenant_id, backfill_id)
    if backfill is None:
        service.finish(job, status=JOB_FAILED, error="The backfill no longer exists.")
        return
    now = datetime.now(timezone.utc)
    try:
        run_backfill(db, backfill, now=now, vendor_transport=transport)
    except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
        logger.exception("doc-feed backfill job %s crashed", job.id)
        db.rollback()
        service.finish(job, status=JOB_FAILED, error=f"Job crashed: {exc}")
        return
    service.finish(job, status=JOB_DONE)


_RUN_HANDLER_DEF = JobHandlerDef(
    DOC_FEED_RUN_JOB_TYPE, run_doc_feed_job, "AutoCount document feed run",
    heartbeats=True,
)
_BACKFILL_HANDLER_DEF = JobHandlerDef(
    DOC_FEED_BACKFILL_JOB_TYPE, run_doc_feed_backfill_job, "AutoCount document feed backfill",
    heartbeats=True,
)


def register_doc_feed_job_handlers() -> None:
    register_job_handler(_RUN_HANDLER_DEF)
    register_job_handler(_BACKFILL_HANDLER_DEF)
