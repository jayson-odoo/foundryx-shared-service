"""The AutoCount ETL beat sweep (plan 22 S3, AC-22-13/14).

ONE indexed query selects every ACTIVE ``sql_db`` task whose next incremental
or reconcile time is due; each is then claimed (a guarded ``UPDATE`` so two
beats ticking the same task never both enqueue), overlap-guarded (a run still
in flight → a ``skipped`` run-history row, no job queued), and enqueued
through the SAME ``autocount_sync`` background job the manual "Run now" button
uses - ``mode='incremental'`` or ``'reconcile'`` (reconcile wins when both are
due).

**The sweep itself does NO extraction** - it selects, claims, guards and
enqueues; ``run_autocount_sync`` (``sync.py``) does the actual work, exactly
as it does for a manual run. **Per-task failure isolation**: one bad task's
exception never stops the sweep or corrupts a sibling task's row (mirrors
``app/workflow_engine/scheduler.reevaluate_time_based``).

**Timezone note (documented per plan §2.4).** Foundryx has NO tenant-level
timezone setting today - only a per-user ``users.timezone`` preference, which
has no natural owner for an unattended scheduled task. So a "Daily at HH:MM"
reconcile is resolved as UTC, both when armed (``EtlService.next_run_times``,
called at activate/resume) and here at the sweep (the SAME pure function,
called fresh against ``now`` so drift never compounds). A genuine tenant
timezone setting is a fair follow-up once a customer needs true local-wall-
clock scheduling in a non-UTC tenant.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.jobs.service import JobService
from app.models.background_job import JOB_RUNNING
from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
from app.models.status import Status
from app.models.tenant import Tenant

from .models import (
    ETL_STATUS_ACTIVE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
    AcSyncRun,
)
from .repositories import SyncJobRepository, SyncRunRepository, WatermarkRepository
from .services.etl_service import EtlService
from .bootstrap import MODULE_NAME as AUTOCOUNT_MODULE_NAME

logger = logging.getLogger("foundryx.autocount")

# S3 review SHOULD-FIX 3: a job wedged in ``running``/``pending`` forever (a
# crashed worker that never reached a terminal status) makes the overlap
# guard fire on EVERY tick - 1440 skip rows/day and no signal an operator can
# act on. Past this age the tick is treated as STALE rather than merely
# in-flight: bounded, one-time, visible.
def _orphan_after() -> timedelta:
    from app.config import settings

    return timedelta(minutes=settings.background_job_orphan_after_minutes)


def sweep_etl_tasks(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The beat tick body. Returns ``{fired, skipped, failed}`` - a plain dict
    so the Celery task can hand it straight back as the task result."""
    now = now or datetime.now(timezone.utc)
    #     !!  A DEACTIVATED SERVICE / SUSPENDED TENANT MUST NEVER BE SWEPT.  !!
    # (S3 review BLOCKER 3.) After a tenant deactivates the autocount Service
    # (``tenant_modules`` INACTIVE - data kept, routes 403) or the tenant
    # itself is suspended/archived, an unguarded sweep keeps extracting their
    # production DB and pushing deletes with nobody able to see or stop it.
    # The join is the SAME canonical lifecycle predicate the platform uses
    # everywhere else (``Tenant.signin_allowed`` - not blocked, not archived)
    # plus the module-active check (mirrors ``active_modules``), done ONE
    # indexed join here rather than N+1 per-row checks in ``_sweep_one``.
    due = (
        db.query(AcEntityConfig)
        .join(Tenant, Tenant.id == AcEntityConfig.tenant_id)
        .join(Status, Status.id == Tenant.status_id)
        .join(
            TenantModule,
            and_(
                TenantModule.tenant_id == AcEntityConfig.tenant_id,
                TenantModule.status == MODULE_STATUS_ACTIVE,
            ),
        )
        .join(
            Module,
            and_(
                Module.id == TenantModule.module_id,
                Module.name == AUTOCOUNT_MODULE_NAME,
            ),
        )
        .filter(
            AcEntityConfig.etl_status == ETL_STATUS_ACTIVE,
            AcEntityConfig.source_impl == SOURCE_IMPL_SQL_DB,
            Status.blocks_access.is_(False),
            Status.is_archived.is_(False),
            or_(
                and_(
                    AcEntityConfig.next_incremental_at.isnot(None),
                    AcEntityConfig.next_incremental_at <= now,
                ),
                and_(
                    AcEntityConfig.next_reconcile_at.isnot(None),
                    AcEntityConfig.next_reconcile_at <= now,
                ),
            ),
        )
        .all()
    )
    fired = skipped = failed = 0
    for config in due:
        try:
            outcome = _sweep_one(db, config, now=now)
        except Exception:  # noqa: BLE001 - one bad task never stops the sweep
            logger.exception(
                "autocount ETL sweep failed for task %s/%s/%s",
                config.tenant_id, config.company_id, config.entity_type,
            )
            db.rollback()
            failed += 1
            continue
        if outcome == "fired":
            fired += 1
        elif outcome == "skipped":
            skipped += 1
    return {"fired": fired, "skipped": skipped, "failed": failed}


def _sweep_one(db: Session, config: AcEntityConfig, *, now: datetime) -> str:
    """One due task's tick. Returns ``"fired" | "skipped" | "not_due"`` (the
    last only possible if a sibling beat won the claim first)."""
    from .sync import AUTOCOUNT_SYNC

    due_incremental = (
        config.next_incremental_at is not None and config.next_incremental_at <= now
    )
    due_reconcile = (
        config.next_reconcile_at is not None and config.next_reconcile_at <= now
    )
    if not due_incremental and not due_reconcile:
        return "not_due"

    # Reconcile wins when both are due (plan §2.6) - the recorded MODE on the
    # job/run; the mechanics for a no-watermark task are the same diff either
    # way (AC-22-12 item 6), the source decides that on its own.
    mode = RUN_MODE_RECONCILE if due_reconcile else RUN_MODE_INCREMENTAL

    #     !!  AN OPEN PASS WINS OVER WHICHEVER SCHEDULE HAPPENED TO FIRE (F3,
    #         review round 2).  !!
    # A paged pass (plan sprint-5/03) can span several ticks (D3). If it is
    # still open when a DIFFERENT schedule fires - e.g. only the incremental
    # cadence is due while a reconcile pass is mid-flight, because the sweep's
    # own claim already re-armed ``next_reconcile_at`` into the future - the
    # tick must continue THAT pass, not silently start a plain incremental
    # one under a mismatched mode (which ``PageCursor.from_watermark_row``
    # would refuse to resume, wasting the tick and leaving the real pass
    # exactly where it was). The open pass's own ``kind`` always wins,
    # regardless of which schedule field was actually due this tick.
    watermark = WatermarkRepository(db).get(
        config.tenant_id, config.company_id, config.entity_type
    )
    if watermark is not None and isinstance(watermark.cursor_json, dict):
        pass_state = watermark.cursor_json.get("pass")
        if isinstance(pass_state, dict) and not pass_state.get("complete", False):
            open_kind = pass_state.get("kind")
            #     !!  A SCHEDULER TICK NEVER RECORDS mode='manual' (NIT,
            #         review round 3).  !!
            # A manual "Run now" can itself open an incomplete pass (an
            # operator-triggered initial load truncated by the budget) - the
            # scheduler continuing it must still record a SCHEDULE-driven
            # mode on the job/run, never the operator's own ``manual``
            # verbatim (a scheduler-fired job claiming to be "manual" is a
            # contradiction in terms and would misreport how the run
            # started). Falls back to incremental, the shorter/default
            # cadence - reconcile only ever opens its OWN kind, so this only
            # ever fires for a continued manual pass.
            if open_kind in (RUN_MODE_INCREMENTAL, RUN_MODE_RECONCILE):
                mode = open_kind
            elif open_kind:
                mode = RUN_MODE_INCREMENTAL

    next_incremental, next_reconcile = EtlService.next_run_times(
        config.source_config or {}, now=now
    )

    # Guarded claim - two beat processes ticking the same task must not both
    # enqueue (mirrors `run_due_workflows`'s claim-before-fire UPDATE). Only
    # the field(s) that were actually due are bumped; the other's due time is
    # left untouched even though `next_run_times` freshly computed a value for
    # it too (both halves are independent pure functions of `now`, so
    # discarding the one that was not due is harmless).
    updates: Dict[Any, Any] = {}
    conditions = []
    if due_incremental:
        updates[AcEntityConfig.next_incremental_at] = next_incremental
        conditions.append(AcEntityConfig.next_incremental_at <= now)
    if due_reconcile:
        updates[AcEntityConfig.next_reconcile_at] = next_reconcile
        conditions.append(AcEntityConfig.next_reconcile_at <= now)
    claimed = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.id == config.id,
            # N3: re-assert ACTIVE on the claim itself, not just the earlier
            # ``due`` SELECT - the task may have been paused/deactivated in
            # the gap between the two.
            AcEntityConfig.etl_status == ETL_STATUS_ACTIVE,
            or_(*conditions),
        )
        .update(updates, synchronize_session=False)
    )
    if not claimed:
        db.rollback()
        return "not_due"
    db.commit()

    tenant_id, company_id, entity_type = (
        config.tenant_id, config.company_id, config.entity_type
    )

    # Overlap guard (AC-22-14) - a still-executing run for this (company,
    # entity) means this tick is skipped, not queued behind it.
    in_flight = SyncJobRepository(db).first_unfinished(
        tenant_id, AUTOCOUNT_SYNC, company_id, entity_type
    )
    if in_flight is not None:
        # Liveness, not age (fix/job-lease-orphan-sweep): a RUNNING job whose worker
        # has not heart-beaten (legacy/pre-checkpoint: not started) for
        # ``background_job_orphan_after_minutes`` is ORPHANED - a deploy
        # drain or a crash left ``running`` behind (prod 2026-09-07, PO sync).
        # Sweep exactly THAT job (failed + its run row closed through the
        # module hook) and carry on with this tick as if nothing were in
        # flight, instead of the old 60-minute JOB_STUCK pause that only a
        # human with SQL could lift. A FRESH in-flight job still skips the
        # tick below (overlap guard, AC-22-14).
        # Only a RUNNING job can be an orphan - a PENDING one of any age is a
        # backlogged queue, and running the tick over it would duplicate the
        # work when it finally starts. And the tick proceeds ONLY when the
        # sweep actually failed that job (== 1): a job that beat again in
        # between, or that another process already swept, is not ours to
        # run over.
        last_alive = in_flight.heartbeat_at or in_flight.started_at or in_flight.created_at
        stale = last_alive is not None and (now - last_alive) > _orphan_after()
        if (
            in_flight.status == JOB_RUNNING
            and stale
            and JobService(db).fail_orphaned_running_jobs(
                older_than=_orphan_after(), now=now, job_id=in_flight.id
            ) == 1
        ):
            logger.warning(
                "autocount scheduler swept orphaned job %s for %s/%s; proceeding with the tick",
                in_flight.id, company_id, entity_type,
            )
            in_flight = None
    if in_flight is not None:
        SyncRunRepository(db).add(
            AcSyncRun(
                tenant_id=tenant_id,
                company_id=company_id,
                entity_type=entity_type,
                job_id=None,
                mode=RUN_MODE_SKIPPED,
                skip_reason=(
                    f"A run for this task was still in progress when the "
                    f"{'reconcile' if mode == RUN_MODE_RECONCILE else 'incremental'} "
                    f"schedule fired; this tick was skipped."
                ),
                started_at=now,
                finished_at=now,
                duration_ms=0,
            )
        )
        db.commit()
        return "skipped"

    try:
        JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC,
            tenant_id=tenant_id,
            payload={"companyId": company_id, "entityType": entity_type, "mode": mode},
        )
    except Exception as exc:  # noqa: BLE001
        # S4 review SHOULD-FIX 4: the claim above already COMMITTED (the due
        # time already advanced), so a failure here is a genuinely LOST tick,
        # not a retried one - invisible unless it is stamped somewhere an
        # operator looks. Write it on a FRESH session bound to the same
        # connection: `db` may be left dirty by the failed flush, and the
        # caller's own `db.rollback()` on this re-raise would silently wipe
        # an error message set on `db` itself before it could be read back.
        fresh = Session(bind=db.get_bind())
        try:
            fresh_config = (
                fresh.query(AcEntityConfig)
                .filter(AcEntityConfig.id == config.id)
                .first()
            )
            if fresh_config is not None:
                fresh_config.last_run_error = (
                    f"Scheduled run could not be enqueued: {exc}"[:4000]
                )
                fresh_config.last_run_error_code = "ENQUEUE_FAILED"
                fresh.commit()
        finally:
            fresh.close()
        raise
    return "fired"
