"""The AutoCount ETL beat sweep (plan 22 S3, AC-22-13/14).

ONE indexed query selects every ACTIVE ``sql_db`` task whose next incremental
or reconcile time is due; each is then claimed (a guarded ``UPDATE`` so two
beats ticking the same task never both enqueue), overlap-guarded (a run still
in flight → a ``skipped`` run-history row, no job queued; a skipped
RECONCILE slot is deferred, not consumed - it stays due and runs on the first
tick after the in-flight run ends), and enqueued
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
from app.models.background_job import JOB_PENDING, JOB_RUNNING
from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
from app.models.status import Status
from app.models.tenant import Tenant

from .models import (
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
    AcSyncRun,
)
from .repositories import SyncJobRepository, SyncRunRepository, WatermarkRepository
from .services.etl_service import EtlService
from .bootstrap import MODULE_NAME as AUTOCOUNT_MODULE_NAME

logger = logging.getLogger("foundryx.autocount")

# The run-history ``skip_reason`` of a reconcile deferred by the overlap guard
# (SS-RECONCILE-SKIP-FIX) - also the prefix the one-row-per-slot dedupe reads.
RECONCILE_DEFERRED_REASON = (
    "A run for this task was still in progress when the reconcile schedule "
    "fired; the reconcile stays due and is retried on the first tick after "
    "that run ends."
)

# S3 review SHOULD-FIX 3: a job wedged in ``running``/``pending`` forever (a
# crashed worker that never reached a terminal status) makes the overlap
# guard fire on EVERY tick - 1440 skip rows/day and no signal an operator can
# act on. Past this age the tick is treated as STALE rather than merely
# in-flight: bounded, one-time, visible.
def _orphan_after() -> timedelta:
    from app.config import settings

    return timedelta(minutes=settings.background_job_orphan_after_minutes)


# sprint-5/11 S2 (incident 2026-09-21) - sibling threshold to ``_orphan_after``
# for a PENDING job whose Celery message was itself lost (never became
# RUNNING, so it has no heartbeat/started_at to judge liveness by).
def _undispatched_after() -> timedelta:
    from app.config import settings

    return timedelta(minutes=settings.background_job_undispatched_after_minutes)


def active_tenant_service_join(query, tenant_id_column):
    """sprint-5/14 (D14) - the SAME canonical tenant-lifecycle + module-active
    predicate ``sweep_etl_tasks`` established (S3 review BLOCKER 3),
    extracted so ``doc_feed.scheduler.sweep_doc_feeds`` can share it
    byte-for-byte rather than cloning the four-way join a second time.
    ``sweep_etl_tasks``'s own behaviour is unchanged - it now calls this
    helper instead of inlining the same joins."""
    return (
        query
        .join(Tenant, Tenant.id == tenant_id_column)
        .join(Status, Status.id == Tenant.status_id)
        .join(
            TenantModule,
            and_(
                TenantModule.tenant_id == tenant_id_column,
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
        .filter(Status.blocks_access.is_(False), Status.is_archived.is_(False))
    )


def sweep_order_key(entity_type: str) -> int:
    """Plan 32 (D11) - the enqueue order of one tick's due tasks: credit and
    debit notes after every other entity (so after invoices and cash sales);
    every other entity keeps its relative order (a stable sort on 0)."""
    from .canonical.documents import ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE

    return 1 if entity_type in (ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE) else 0


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
        active_tenant_service_join(db.query(AcEntityConfig), AcEntityConfig.tenant_id)
        .filter(
            AcEntityConfig.etl_status == ETL_STATUS_ACTIVE,
            AcEntityConfig.source_impl.in_(
                (SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP)
            ),
            # sprint-5/10 (AC-10-13) - a ``pull`` task never runs on the
            # sweep at all: it is extracted on a consumer/operator request,
            # never on a schedule.
            AcEntityConfig.delivery_mode == DELIVERY_MODE_PUSH,
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
    # Plan 32 (D11) - within one tick, invoices and cash sales are enqueued
    # before credit and debit notes (contract 12: IV/CS before CN/DN). Best
    # effort only: the jobs run independently, and the CRM fills a note's
    # link when its invoice lands later, so the order is never load-bearing.
    due.sort(key=lambda config: sweep_order_key(config.entity_type))
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
    # Plan 33 - the failure-alert check rides the same tick; its own crash
    # never changes what the sweep reports or whether the next tick enqueues.
    try:
        from .alerts import evaluate_integration_alerts

        evaluate_integration_alerts(db, now=now)
    except Exception:  # noqa: BLE001 - alerting must never break the sweep
        logger.exception("autocount failure-alert check failed")
        db.rollback()
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
    # The reconcile slot exactly as it stood before this tick's claim - a
    # tick that ends up NOT running a reconcile puts it back (see
    # ``_keep_reconcile_due``).
    reconcile_slot = config.next_reconcile_at

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
        # Only a RUNNING job is judged here - a PENDING one is the sibling
        # branch below's business (a job cannot be both "never dispatched"
        # and "started"). And the tick proceeds ONLY when the sweep actually
        # failed that job (== 1): a job that beat again in between, or that
        # another process already swept, is not ours to run over.
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
        # sprint-5/11 S2 (incident 2026-09-21) - a sibling branch to the
        # RUNNING one above: a PENDING job (``started_at`` NULL) whose
        # Celery message was itself lost never becomes RUNNING at all, so it
        # never trips the orphan branch above and would otherwise sit
        # skipped forever (a deploy restarted the worker mid-``pending``,
        # the message never arrived, and every tick afterwards wrote a
        # skip row - "A run for this task was still in progress" - until the
        # owner reset the row by hand in SQL, 8+ hours later). Sweep exactly
        # THAT job once it is stale past
        # ``background_job_undispatched_after_minutes`` and carry on with
        # this tick as if nothing were in flight, one-for-one with the
        # RUNNING branch. A job that is merely PENDING and fresh - queued,
        # not lost - is left untouched; the tick below still skips for it
        # exactly as it does today (AC-11-54).
        undispatched_stale = (
            in_flight.created_at is not None
            and (now - in_flight.created_at) > _undispatched_after()
        )
        if (
            in_flight.status == JOB_PENDING
            and in_flight.started_at is None
            and undispatched_stale
            and JobService(db).fail_undispatched_pending_jobs(
                older_than=_undispatched_after(), now=now, job_id=in_flight.id
            ) == 1
        ):
            logger.warning(
                "autocount scheduler swept undispatched job %s for %s/%s; proceeding with the tick",
                in_flight.id, company_id, entity_type,
            )
            in_flight = None
    if in_flight is not None:
        runs = SyncRunRepository(db)
        if due_reconcile:
            #     !!  A SKIPPED RECONCILE IS DEFERRED, NEVER CONSUMED
            #         (SS-RECONCILE-SKIP-FIX, prod 27 Oct).  !!
            # The claim above already re-armed ``next_reconcile_at`` to the
            # NEXT day; leaving it there lost the whole day's reconcile (and
            # with it every line-only change the incremental cannot see).
            # Put the slot back so it stays due: every following tick meets
            # this same guard until the in-flight run ends, then the first
            # tick after that claims and runs the reconcile exactly once.
            _keep_reconcile_due(db, config.id, armed=next_reconcile, slot=reconcile_slot)
            # One skip row per deferred slot, not one per minute while the
            # run is in flight - unless the incremental cadence was ALSO due,
            # which has always written its own row per cadence.
            write_row = due_incremental or not runs.has_skip_since(
                tenant_id, company_id, entity_type,
                since=reconcile_slot, reason_prefix=RECONCILE_DEFERRED_REASON,
            )
            reason = RECONCILE_DEFERRED_REASON
        else:
            write_row = True
            reason = (
                "A run for this task was still in progress when the incremental "
                "schedule fired; this tick was skipped."
            )
        if write_row:
            runs.add(
                AcSyncRun(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    job_id=None,
                    mode=RUN_MODE_SKIPPED,
                    skip_reason=reason,
                    started_at=now,
                    finished_at=now,
                    duration_ms=0,
                )
            )
        db.commit()
        return "skipped"

    _refill_empty_line_check(db, config)

    try:
        JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC,
            tenant_id=tenant_id,
            payload={"companyId": company_id, "entityType": entity_type, "mode": mode},
        )
    except Exception as exc:  # noqa: BLE001
        if due_reconcile and mode != RUN_MODE_RECONCILE:
            # The open-pass deferral below must not be lost to a failed
            # enqueue either (nothing was queued, so no overlap risk).
            db.rollback()
            _keep_reconcile_due(db, config.id, armed=next_reconcile, slot=reconcile_slot)
            db.commit()
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
    if due_reconcile and mode != RUN_MODE_RECONCILE:
        # An open non-reconcile pass won this tick's mode (F3 above), so the
        # reconcile that was due did not run - keep it due rather than lose
        # it to the claim's re-arm. Done AFTER the enqueue: the job now
        # exists, so a sibling beat that claims the slot meanwhile meets the
        # overlap guard instead of double-enqueueing.
        _keep_reconcile_due(db, config.id, armed=next_reconcile, slot=reconcile_slot)
        db.commit()
    return "fired"


def _refill_empty_line_check(db: Session, config: AcEntityConfig) -> None:
    """SS-RECONCILE-SKIP-FIX (owner OK 27 Oct): a document task whose
    line-check query is empty gets it refilled from its preset right before
    the run is enqueued (the deploy-time refill covers the rest). A Python
    check first, so a task that has one costs no query. Never fails the tick:
    a refill problem is logged and the run goes ahead as before."""
    from .backfill import refill_empty_fingerprint_queries
    from .presets import DOCUMENT_PRESETS

    if config.entity_type not in DOCUMENT_PRESETS:
        return
    current = (config.source_config or {}).get("fingerprintQuery")
    if isinstance(current, str) and current.strip():
        return
    try:
        refill_empty_fingerprint_queries(db, config_ids=[config.id])
        db.commit()
    except Exception:  # noqa: BLE001 - a refill never blocks the run
        db.rollback()
        logger.exception("autocount line-check refill failed for task %s", config.id)


def _keep_reconcile_due(
    db: Session, config_id: str, *, armed: Optional[datetime], slot: Optional[datetime]
) -> None:
    """Undo this tick's re-arm of ``next_reconcile_at`` (back to ``slot``,
    still ``<= now`` so the next tick finds it due). Guarded on the value the
    claim wrote: if anything else re-armed the task since to a DIFFERENT value
    (an activate/resume with a changed schedule), that value wins. A re-arm
    that recomputes the very same slot is indistinguishable and gets the old
    slot back - at worst one extra reconcile, never a lost one."""
    if slot is None or armed is None:
        return
    db.query(AcEntityConfig).filter(
        AcEntityConfig.id == config_id,
        AcEntityConfig.next_reconcile_at == armed,
    ).update({AcEntityConfig.next_reconcile_at: slot}, synchronize_session=False)
