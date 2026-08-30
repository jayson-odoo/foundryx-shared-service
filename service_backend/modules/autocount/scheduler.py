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
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.jobs.service import JobService

from .models import (
    ETL_STATUS_ACTIVE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
    AcSyncRun,
)
from .repositories import SyncJobRepository, SyncRunRepository
from .services.etl_service import EtlService

logger = logging.getLogger("foundryx.autocount")


def sweep_etl_tasks(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The beat tick body. Returns ``{fired, skipped, failed}`` - a plain dict
    so the Celery task can hand it straight back as the task result."""
    now = now or datetime.now(timezone.utc)
    due = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.etl_status == ETL_STATUS_ACTIVE,
            AcEntityConfig.source_impl == SOURCE_IMPL_SQL_DB,
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
        .filter(AcEntityConfig.id == config.id, or_(*conditions))
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

    JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC,
        tenant_id=tenant_id,
        payload={"companyId": company_id, "entityType": entity_type, "mode": mode},
    )
    return "fired"
