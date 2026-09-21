"""Background-job service (sprint-4/10) - create · claim · enqueue · progress.

Mirrors the import-engine service: eager-inline in dev/test (``celery_task_
always_eager``) vs Celery ``.delay`` in prod; an atomic status-claim admits
exactly one worker; a handler crash is fully isolated (job → failed, logged,
never propagated). Resume is handler-driven: the handler reads ``cursor_json``
and continues.
"""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.registry import handler_for, types_that_heartbeat
from app.jobs.repository import BackgroundJobRepository
from app.models.background_job import (
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)

logger = logging.getLogger("foundryx.jobs")


class JobService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BackgroundJobRepository(db)

    # ── create + enqueue ─────────────────────────────────────────────────────

    def create(
        self,
        *,
        type: str,
        tenant_id: str,
        actor_user_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> BackgroundJob:
        """Create a pending job row. Validates the ``type`` is registered up
        front (loud) so an unrunnable job is never persisted."""
        handler_for(type)  # raises UnknownJobType if not registered
        job = BackgroundJob(
            tenant_id=tenant_id,
            type=type,
            status=JOB_PENDING,
            actor_user_id=actor_user_id,
            payload_json=payload or None,
        )
        self.repo.add(job)
        self.db.commit()
        return job

    def enqueue(self, job_id: str) -> None:
        """Eager (dev/test) runs INLINE on this session; else Celery, routed
        onto the handler's declared queue when it has one (sprint-5:
        ``meetings.transcribe`` -> ``stt``, mirroring how ``enqueue_bot_run``
        targets the dedicated ``bots`` queue), the worker's default queue
        otherwise."""
        if settings.celery_task_always_eager:
            run_job(self.db, job_id)
            return
        from app.jobs.registry import queue_for_type
        from app.jobs.worker import run_job_task

        job = self.repo.get_unscoped(job_id)
        queue = queue_for_type(job.type) if job is not None else None
        if queue:
            run_job_task.apply_async(args=[job_id], queue=queue)
        else:
            run_job_task.delay(job_id)

    def create_and_enqueue(
        self,
        *,
        type: str,
        tenant_id: str,
        actor_user_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> BackgroundJob:
        job = self.create(
            type=type, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=payload
        )
        self.enqueue(job.id)
        return job

    # ── reads ────────────────────────────────────────────────────────────────

    def list(
        self,
        tenant_id: str,
        *,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ):
        return self.repo.list(
            tenant_id, job_type=job_type, status=status, page=page, page_size=page_size
        )

    def get(self, tenant_id: str, job_id: str) -> Optional[BackgroundJob]:
        return self.repo.get(tenant_id, job_id)

    # ── claim (exactly-once) ─────────────────────────────────────────────────

    def claim(self, job_id: str, *, from_status: str = JOB_PENDING) -> bool:
        """Atomic status-claim → running. Returns True for the single winner."""
        claimed = self.repo.claim(job_id, from_status)
        self.db.commit()
        return claimed

    # ── progress + resume helpers ────────────────────────────────────────────

    def set_total(self, job: BackgroundJob, total: int) -> None:
        job.progress_total = total
        self.db.commit()

    def advance(self, job: BackgroundJob, *, done: int = 0, failed: int = 0) -> None:
        job.progress_done = (job.progress_done or 0) + done
        job.progress_failed = (job.progress_failed or 0) + failed
        self.db.commit()

    def set_cursor(self, job: BackgroundJob, cursor: Optional[dict]) -> None:
        job.cursor_json = cursor
        self.db.commit()

    def log(self, job: BackgroundJob, message: str, *, level: str = "info") -> None:
        """Append a milestone log line to the job (surfaced on the detail page).
        Reassigns a FRESH list so SQLAlchemy tracks the change (a plain JSON
        column drops in-place mutation - the house gotcha). Milestones only."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
        }
        job.logs_json = list(job.logs_json or []) + [entry]
        self.db.commit()
        logger.info("[job %s] %s", job.id, message)

    def finish(
        self,
        job: BackgroundJob,
        *,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        job.status = status
        if result is not None:
            job.result_json = result
        if error is not None:
            job.error = error
        if status in JOB_TERMINAL_STATUSES:
            job.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    # ── liveness (fix/job-lease-orphan-sweep) ────────────────────────────────

    ORPHANED_ERROR = (
        "Interrupted: the worker stopped (deploy or crash) before this run "
        "finished; the next run re-offers its staged rows"
    )

    # sprint-5/11 S1 (AC-11-83) - the cooperative SoftTimeLimitExceeded
    # sentence. Deliberately NOT the generic "Job crashed: ..." phrasing:
    # this path is a clean, expected stop at a configured bound, not a crash.
    SOFT_TIME_LIMIT_ERROR = (
        "Stopped: this run exceeded its soft time limit; the next run "
        "re-offers its staged rows"
    )

    # sprint-5/11 S2 (AC-11-50, incident 2026-09-21) - a PENDING job whose
    # Celery message was lost never reaches a worker at all, so it has no
    # heartbeat/started_at to judge liveness by; this is a DIFFERENT
    # incident from ORPHANED_ERROR (a worker that started the job then
    # died) and must not share its sentence. Not "Job crashed: ..." either -
    # this is a clean, expected recovery at a configured bound.
    UNDISPATCHED_ERROR = (
        "Interrupted: the worker never picked this job up (the queued "
        "message was lost)."
    )

    def heartbeat(self, job_id: str, *, now: Optional[datetime] = None) -> bool:
        """Stamp ``heartbeat_at`` on a RUNNING job in its OWN short transaction.

        Same shape as ``workflow_engine.serialization.touch_run_heartbeat``:
        one UPDATE on a connection taken straight from the session's bind,
        never the run's session - the run holds uncommitted state (a watermark
        advance, staged rows) that must stay uncommitted until the run decides.
        On Postgres the row is skipped rather than waited on. Returns True when
        a row was stamped. Callers treat it as best-effort (a failed heartbeat
        is logged, never allowed to fail the run).
        """
        table = BackgroundJob.__table__
        bind = self.db.get_bind()
        target = select(table.c.id).where(
            table.c.id == job_id, table.c.status == JOB_RUNNING
        )
        if bind.dialect.name == "postgresql":
            target = target.with_for_update(skip_locked=True)
        stmt = (
            update(table)
            .where(table.c.id == target.scalar_subquery())
            .values(heartbeat_at=now or datetime.now(timezone.utc))
        )
        with bind.begin() as conn:
            return conn.execute(stmt).rowcount > 0

    def fresh_status(self, job_id: str) -> Optional[str]:
        """The job's status re-read FRESH from the DB (a scalar query, so a
        stale in-memory ``job`` object is bypassed) - for the heartbeat
        fences: a 0-row beat on a row that is still RUNNING is Postgres
        ``SKIP LOCKED``, not a lost lease."""
        return (
            self.db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar()
        )

    def is_running(self, job_id: str) -> bool:
        return self.fresh_status(job_id) == JOB_RUNNING

    def fail_orphaned_running_jobs(
        self,
        *,
        older_than: Optional[timedelta] = None,
        now: Optional[datetime] = None,
        job_id: Optional[str] = None,
    ) -> int:
        """Fail every RUNNING job whose worker is gone. Returns how many.

        "Gone" = ``coalesce(heartbeat_at, started_at, created_at)`` older than
        ``older_than`` (default ``settings.background_job_orphan_after_minutes``).
        A deploy's 30s drain or a crash leaves ``running`` behind - the status
        is not rolled back on death - and every scheduler tick then skips the
        task for a run that will never finish (prod 2026-09-07, PO sync).

        Each orphan is marked ``failed`` with ``ORPHANED_ERROR`` and a
        ``finished_at``; then every on-disk module's ``on_job_orphaned(db,
        job, now=)`` hook (discovered like ``install_tenant``, through
        ``modules.<name>.bootstrap``, whether or not the module is installed
        for that tenant) may close its OWN bookkeeping for that job - core
        never imports a module. The module decides by ``job.type``
        (autocount closes the open ``ac_sync_run`` row; staged rows are left
        alone so the next run re-offers them). A hook failure is logged and
        never blocks the sweep. Idempotent: a job already failed is not
        matched again. ``job_id`` narrows the sweep to one job (the scheduler
        sweeps exactly the stale in-flight job it would otherwise skip for).
        """
        current = now or datetime.now(timezone.utc)
        threshold = older_than or timedelta(
            minutes=settings.background_job_orphan_after_minutes
        )
        cutoff = current - threshold
        # Only a type that DECLARED it beats can be judged by a stale beat
        # (``JobHandlerDef.heartbeats``) - a long job of a silent type (a
        # 45-minute meetings transcription) must never be swept.
        beating_types = types_that_heartbeat()
        if not beating_types:
            # S15 (review round 2): a sweep that runs before `load_modules`
            # registers any `heartbeats` job type finds nothing to judge and
            # silently no-ops - which looks identical to "nothing is stuck"
            # from the caller's side. Self-report so a mis-ordered startup
            # sweep (or a module that forgot to declare `heartbeats=True`)
            # is visible in the logs rather than inferred from a stuck job.
            logger.warning(
                "fail_orphaned_running_jobs: no job type declares heartbeats - "
                "sweep is a no-op (modules not loaded yet?)"
            )
            return 0
        query = self.db.query(BackgroundJob).filter(
            BackgroundJob.status == JOB_RUNNING,
            BackgroundJob.type.in_(beating_types),
            func.coalesce(
                BackgroundJob.heartbeat_at,
                BackgroundJob.started_at,
                BackgroundJob.created_at,
            )
            < cutoff,
        )
        if job_id is not None:
            query = query.filter(BackgroundJob.id == job_id)
        orphans = query.all()
        if not orphans:
            return 0
        for job in orphans:
            job.status = JOB_FAILED
            job.error = self.ORPHANED_ERROR
            job.finished_at = current
            logger.error(
                "background job %s (%s, tenant %s) orphaned: no heartbeat since %s; failed",
                job.id, job.type, job.tenant_id,
                (job.heartbeat_at or job.started_at or job.created_at),
            )
            close_module_bookkeeping(self.db, job, now=current)
        self.db.commit()
        return len(orphans)

    def fail_undispatched_pending_jobs(
        self,
        *,
        older_than: Optional[timedelta] = None,
        now: Optional[datetime] = None,
        job_id: Optional[str] = None,
    ) -> int:
        """Fail every PENDING job whose Celery message was never delivered.
        Returns how many.

        "Never delivered" = ``status == pending`` AND ``started_at IS NULL``
        AND ``created_at`` older than ``older_than`` (default
        ``settings.background_job_undispatched_after_minutes``). UNLIKE
        ``fail_orphaned_running_jobs`` this is NOT restricted to
        ``heartbeats=True`` types - a lost message is type-agnostic
        (AC-11-50): the job never started, so it never had a chance to
        declare liveness at all.

        Each undispatched job is marked ``failed`` with
        ``UNDISPATCHED_ERROR`` and a ``finished_at``, then fanned out
        through the SAME ``close_module_bookkeeping`` helper the running
        sweep and the soft-time-limit path already share (S1), so a module's
        open bookkeeping (e.g. an ``ac_sync_run`` row) closes the same way
        regardless of which sweep caught the job.

        Never re-enqueues anything (D12/D13, R6): re-dispatch collides with
        ``run_job``'s RUNNING crash-resume branch if the original lost
        message is somehow delivered late after a re-enqueue - two workers
        could execute the same job and double-push. Failing costs one
        minute; the next tick enqueues a FRESH job. Idempotent: a job
        already failed is not matched again. ``job_id`` narrows the sweep to
        one job (the scheduler sweeps exactly the stale in-flight job it
        would otherwise skip for).
        """
        current = now or datetime.now(timezone.utc)
        threshold = older_than or timedelta(
            minutes=settings.background_job_undispatched_after_minutes
        )
        cutoff = current - threshold
        query = self.db.query(BackgroundJob).filter(
            BackgroundJob.status == JOB_PENDING,
            BackgroundJob.started_at.is_(None),
            BackgroundJob.created_at < cutoff,
        )
        if job_id is not None:
            query = query.filter(BackgroundJob.id == job_id)
        undispatched = query.all()
        if not undispatched:
            return 0
        for job in undispatched:
            job.status = JOB_FAILED
            job.error = self.UNDISPATCHED_ERROR
            job.finished_at = current
            logger.error(
                "background job %s (%s, tenant %s) undispatched: queued since %s "
                "with no worker pickup; failed",
                job.id, job.type, job.tenant_id, job.created_at,
            )
            close_module_bookkeeping(self.db, job, now=current)
        self.db.commit()
        return len(undispatched)

    # ── retention ─────────────────────────────────────────────────────────────

    def prune(self, *, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=settings.background_job_retention_days)
        deleted = self.repo.prune_terminal(older_than=cutoff)
        self.db.commit()
        return deleted


def close_module_bookkeeping(
    db: Session, job: BackgroundJob, *, now: Optional[datetime] = None
) -> None:
    """Fan out every installed module's ``on_job_orphaned(db, job[, now=])``
    hook for ONE already-terminal job (sprint-5/11 S1, plan sec 2.6). The
    SAME per-hook-SAVEPOINT shape ``fail_orphaned_running_jobs`` used inline
    before this extraction, now shared by three closers - the orphan sweep,
    the (S2) undispatched-pending sweep, and the ``SoftTimeLimitExceeded``
    path in ``run_job`` (AC-11-83) - so they can never drift apart.

    The CALLER must already have set ``job.status``/``.error``/
    ``.finished_at`` before this runs - it only closes each module's OWN
    bookkeeping for the job (autocount closes an open ``ac_sync_run`` row;
    staged rows are left alone so the next run re-offers them). A hook
    failure is logged and never blocks its siblings or the caller's commit.
    """
    current = now or datetime.now(timezone.utc)
    for module_name, hook in _orphan_hooks():
        # A SAVEPOINT per hook: a failing hook rolls back only its own
        # writes, so on Postgres it cannot leave the session in the aborted
        # state that would poison the caller's own commit.
        try:
            with db.begin_nested():
                # ``now=`` only when the hook takes it (the caller's clock,
                # so run and job timestamps agree); the minimal contract
                # stays ``hook(db, job)``.
                if "now" in inspect.signature(hook).parameters:
                    hook(db, job, now=current)
                else:
                    hook(db, job)
        except Exception:  # noqa: BLE001 - one module must not block the caller
            logger.exception(
                "module '%s' on_job_orphaned failed for job %s", module_name, job.id
            )


def run_job(db: Session, job_id: str) -> Optional[BackgroundJob]:
    """Worker entry point. Claims a pending job (exactly-once), dispatches the
    registered handler, and isolates any handler failure (job → failed, logged).
    A job already RUNNING is a crash-resume: the handler re-reads ``cursor_json``
    and continues from where it stopped."""
    service = JobService(db)
    repo = service.repo
    job = repo.get_unscoped(job_id)
    if job is None:
        return None

    if job.status == JOB_PENDING:
        if not service.claim(job_id):  # lost the race → another worker owns it
            return repo.get_unscoped(job_id)
    elif job.status != JOB_RUNNING:
        # terminal / needs_review - nothing to run here.
        return job

    job = repo.get_unscoped(job_id)
    try:
        handler_def = handler_for(job.type)
    except Exception:  # noqa: BLE001 - unknown type, mark failed + log
        logger.exception("no handler for job %s (type=%s)", job_id, job.type)
        db.rollback()
        job = repo.get_unscoped(job_id)
        if job is not None:
            service.finish(job, status=JOB_FAILED, error=f"No handler for type '{job.type}'.")
        return job

    try:
        handler_def.handler(db, job)
    except SoftTimeLimitExceeded:
        # sprint-5/11 S1 (AC-11-83) - a wedged handler is cut off by Celery's
        # cooperative soft-limit signal. This is caught BEFORE the generic
        # `except Exception` below (SoftTimeLimitExceeded IS an Exception
        # subclass, so the generic branch would otherwise swallow it with
        # the wrong "Job crashed: " phrasing and, critically, WITHOUT closing
        # any module bookkeeping - exactly the open-`ac_sync_run` symptom
        # this whole plan exists to fix). Never re-raised: a worker that let
        # this propagate would crash the ForkPoolWorker instead of failing
        # the job cleanly.
        logger.error("background job %s (type=%s) hit its soft time limit", job_id, job.type)
        db.rollback()
        job = repo.get_unscoped(job_id)
        if job is not None and job.status not in JOB_TERMINAL_STATUSES:
            service.finish(
                job, status=JOB_FAILED, error=JobService.SOFT_TIME_LIMIT_ERROR
            )
            close_module_bookkeeping(db, job)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - full isolation, never propagate
        logger.exception("background job %s (type=%s) crashed", job_id, job.type)
        db.rollback()
        job = repo.get_unscoped(job_id)
        if job is not None and job.status not in JOB_TERMINAL_STATUSES:
            service.finish(job, status=JOB_FAILED, error=f"Job crashed: {exc}")
    return repo.get_unscoped(job_id)


def prune_jobs(db: Session, *, now: Optional[datetime] = None) -> int:
    """Beat housekeeping - delete terminal jobs past the retention window."""
    return JobService(db).prune(now=now)


def _orphan_hooks() -> Iterable[tuple]:
    """``(module_name, hook)`` for every on-disk module whose bootstrap
    exposes ``on_job_orphaned`` - the same discovery ``AppStoreService`` uses
    for ``install_tenant``; imported lazily so the jobs core stays free of the
    module loader at import time."""
    from app.module_loader import discover_manifests
    from app.services.app_store_service import module_hooks

    for manifest in discover_manifests():
        name = manifest["module_name"]
        hooks = module_hooks(name)
        hook = getattr(hooks, "on_job_orphaned", None) if hooks else None
        if callable(hook):
            yield name, hook


def sweep_orphaned_jobs(db: Session) -> int:
    """Startup entry point: fail every orphaned RUNNING job (see
    ``JobService.fail_orphaned_running_jobs``) with the configured threshold
    passed explicitly. Returns the count."""
    return JobService(db).fail_orphaned_running_jobs(
        older_than=timedelta(minutes=settings.background_job_orphan_after_minutes)
    )


def sweep_undispatched_pending_jobs(db: Session) -> int:
    """Entry point: fail every stale PENDING job whose message was never
    delivered (see ``JobService.fail_undispatched_pending_jobs``) with the
    configured threshold passed explicitly. Returns the count."""
    return JobService(db).fail_undispatched_pending_jobs(
        older_than=timedelta(minutes=settings.background_job_undispatched_after_minutes)
    )
