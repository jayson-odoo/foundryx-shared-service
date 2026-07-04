"""Schedule trigger drain (plan sprint-2/09 D9) — a single minute-tick.

``compute_next_run_at`` turns a 5-field cron + IANA timezone into the next UTC
fire time (stored on ``workflows.next_run_at``). ``run_due_workflows`` is the
beat task body (60s): select due rows, CLAIM each with a guarded ``UPDATE`` (so
two beats can't double-fire), enqueue a run, and advance ``next_run_at``.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy.orm import Session

from app.models.workflow import (
    RUN_PENDING,
    TRIGGER_SCHEDULE,
    Workflow,
    WorkflowVersion,
)

logger = logging.getLogger("dreamz.workflows.scheduler")


def _zone(tzname: str):
    if not tzname:
        return timezone.utc
    try:
        return ZoneInfo(tzname)
    except Exception:  # noqa: BLE001 — bad tz falls back to UTC, never explodes
        return timezone.utc


def compute_next_run_at(cron_expr: str, tzname: str = "", *, after: Optional[datetime] = None) -> datetime:
    """Next fire time as aware-UTC. The cron is interpreted in ``tzname`` (so
    '0 9 * * *' means 09:00 local), then converted to UTC for storage."""
    base = after or datetime.now(timezone.utc)
    zone = _zone(tzname)
    local_base = base.astimezone(zone)
    nxt = croniter(cron_expr, local_base).get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=zone)
    return nxt.astimezone(timezone.utc)


def _published_trigger_config(db: Session, wf: Workflow) -> Dict[str, Any]:
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).first()
    if version is None:
        return {}
    for node in (version.definition_json or {}).get("nodes", []):
        if node.get("kind") == "trigger":
            return node.get("config") or {}
    return {}


def run_due_workflows(db: Session, *, now: Optional[datetime] = None) -> int:
    """Fire every scheduled workflow whose ``next_run_at`` has passed. Returns
    the number of runs enqueued."""
    from app.config import settings

    now = now or datetime.now(timezone.utc)
    due = (
        db.query(Workflow)
        .filter(
            Workflow.trigger_type == "schedule.cron",
            Workflow.is_active.is_(True),
            Workflow.is_trashed.is_(False),
            Workflow.current_version_id.isnot(None),
            Workflow.next_run_at.isnot(None),
            Workflow.next_run_at <= now,
        )
        .all()
    )
    fired = 0
    for wf in due:
        config = _published_trigger_config(db, wf)
        cron_expr = str(config.get("cron") or "")
        if not cron_expr:
            continue
        next_at = compute_next_run_at(cron_expr, str(config.get("timezone") or ""), after=now)
        # Claim: advance next_run_at guarded on the still-due value (idempotent
        # under two concurrent beats — only the winner's UPDATE hits a row).
        claimed = (
            db.query(Workflow)
            .filter(Workflow.id == wf.id, Workflow.next_run_at <= now)
            .update({Workflow.next_run_at: next_at}, synchronize_session=False)
        )
        if not claimed:
            continue
        version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).first()
        run = _make_run(wf, version, now)
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()
        fired += 1
        if settings.celery_task_always_eager:
            from app.workflow_engine.executor import run_workflow

            run_workflow(db, run_id)
        else:
            from app.workflow_engine.worker import run_workflow_task

            run_workflow_task.delay(run_id)
    return fired


def prune_runs(db: Session, *, now: Optional[datetime] = None) -> int:
    """Housekeeping (plan sprint-2/10 D4) — delete workflow runs older than the
    retention window, PER TENANT (plan 10 follow-up): each tenant's retention is
    its ``WorkflowSettings.run_retention_days`` override, else the global default
    (``settings.workflow_run_retention_days``). Child ``workflow_run_nodes`` go
    first so the cascade is correct regardless of the DB's FK enforcement
    (Postgres ON DELETE CASCADE vs SQLite's pragma being off in tests). Returns
    the total number of runs deleted."""
    from app.config import settings
    from app.models.workflow import WorkflowRun, WorkflowRunNode, WorkflowSettings

    now = now or datetime.now(timezone.utc)
    default_days = settings.workflow_run_retention_days
    overrides = {
        s.tenant_id: s.run_retention_days
        for s in db.query(WorkflowSettings).filter(WorkflowSettings.run_retention_days.isnot(None))
    }
    tenant_ids = [row[0] for row in db.query(WorkflowRun.tenant_id).distinct()]

    deleted = 0
    for tenant_id in tenant_ids:
        days = overrides.get(tenant_id, default_days)
        cutoff = now - timedelta(days=days)
        old_run_ids = db.query(WorkflowRun.id).filter(
            WorkflowRun.tenant_id == tenant_id, WorkflowRun.created_at < cutoff
        )
        db.query(WorkflowRunNode).filter(
            WorkflowRunNode.run_id.in_(old_run_ids.scalar_subquery())
        ).delete(synchronize_session=False)
        deleted += (
            db.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant_id, WorkflowRun.created_at < cutoff)
            .delete(synchronize_session=False)
        )
    db.commit()
    return deleted


def reevaluate_time_based(db: Session) -> int:
    """Derived status time sweep (sprint-4/03 G4) — re-evaluate records whose
    TIME-conditioned auto edges (e.g. invoice Overdue when due_date < now) the
    event bus can't catch, since no write fires when the clock merely advances.

    For every registered entity flagged ``has_time_auto_edges`` it pulls the
    entity's COARSE candidate set and re-evaluates each, per-record committed so
    one failure never aborts the batch (mirrors the workflow beat's isolation).
    reevaluate fail-closes anything that doesn't actually qualify. Returns the
    number of records that advanced."""
    from app.services.status_machine import reevaluate
    from app.status_engine.registry import list_status_entities

    advanced = 0
    for entity in list_status_entities():
        if not entity.has_time_auto_edges or entity.time_candidates is None:
            continue
        try:
            candidates = entity.time_candidates(db) or []
        except Exception:  # noqa: BLE001 — a bad candidate query never kills the tick
            logger.exception("time-based candidate query failed: %s", entity.entity_type)
            db.rollback()
            continue
        for record in candidates:
            try:
                hops = reevaluate(
                    db,
                    entity.entity_type,
                    record,
                    tenant_id=getattr(record, "tenant_id", None),
                )
                db.commit()
                if hops:
                    advanced += 1
            except Exception:  # noqa: BLE001 — isolate one record's failure
                logger.exception(
                    "time-based reevaluate failed: %s %s",
                    entity.entity_type,
                    getattr(record, "id", None),
                )
                db.rollback()
    return advanced


def simulate_entity_sweep(db, entity_type, tenant_id, as_of, apply=False):
    """Admin date-simulation (sprint-4/03 Slice 6) — run ONE entity's time sweep
    AS-OF ``as_of`` (the injectable clock), tenant-scoped, returning the records
    that would advance: ``[{id,label,fromId,toId}]``.

    ``apply=False`` (default) = DRY-RUN: a single ``rollback`` at the end discards
    everything (the after_rollback listener clears the buffered events too), so
    nothing persists and no events/notifications fire — a side-effect-free preview.
    ``apply=True`` = a single ``commit`` (transitions persist, events drain). A
    record whose ``reevaluate`` raises is logged + skipped (the others still
    preview); ``reevaluate`` validates before mutating, so a skip leaves no
    half-applied row in the common path."""
    from app.clock import clock_override
    from app.services.status_machine import reevaluate
    from app.status_engine.registry import get_status_entity

    entity = get_status_entity(entity_type)
    if entity is None or not entity.has_time_auto_edges or entity.time_candidates is None:
        return []
    results: list = []
    attr = entity.status_attr
    with clock_override(as_of):
        try:
            candidates = [
                r
                for r in (entity.time_candidates(db) or [])
                if getattr(r, "tenant_id", None) == tenant_id
            ]
        except Exception:  # noqa: BLE001
            logger.exception("simulate candidate query failed: %s", entity_type)
            db.rollback()
            return []
        for record in candidates:
            before = getattr(record, attr)
            try:
                reevaluate(db, entity_type, record, tenant_id=tenant_id)
            except Exception:  # noqa: BLE001 — isolate one record; preview the rest
                logger.exception(
                    "simulate reevaluate failed: %s %s", entity_type,
                    getattr(record, "id", None),
                )
                continue
            after = getattr(record, attr)
            if after != before:
                results.append({
                    "id": getattr(record, "id", None),
                    "label": str(getattr(record, entity.record_label_attr, "") or record.id),
                    "fromId": before,
                    "toId": after,
                })
        # DRY-RUN rolls back (nothing persists, no events drain); APPLY commits.
        if apply:
            db.commit()
        else:
            db.rollback()
    return results


def _make_run(wf: Workflow, version: WorkflowVersion, now: datetime):
    from app.models.workflow import WorkflowRun

    return WorkflowRun(
        tenant_id=wf.tenant_id,
        workflow_id=wf.id,
        version_id=wf.current_version_id,
        version_number=version.version_number if version else 0,
        status=RUN_PENDING,
        triggered_by=TRIGGER_SCHEDULE,
        definition_snapshot_json=json.loads(json.dumps(version.definition_json)) if version else {},
        trigger_payload_json={"triggeredBy": TRIGGER_SCHEDULE, "firedAt": now.isoformat()},
        depth=0,
    )
