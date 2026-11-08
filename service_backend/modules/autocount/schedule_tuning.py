"""SS-SO-FAST-QUEUE - move every ETL reconcile off working hours (owner 8 Nov).

The owner's prod probe found reconciles stored as UTC "Daily at" times that
land inside Malaysian working hours (Sorento SO reconcile 04:18 UTC = 12:18
MYT, 8-10 minutes on the shared `jobs` worker). This module PLANS and APPLIES
one idempotent change set, run by the owner through
``python -m scripts.autocount_reconcile_off_hours`` (dry-run by default):

* every push task with a ``dailyAt`` reconcile gets ``reconcileTimezone =
  Asia/Kuala_Lumpur`` and a reconcile time staggered across 02:00-05:00 MYT
  (documents first, then masters; deterministic order, so a re-run proposes
  the same slots and changes nothing);
* every document task (not the AR snapshot) with a watermark gets a 1-minute
  incremental; every sales_order task with a watermark gets a 30-second one
  (owner 8 Nov "go 30s" - Sorento SO and Mocha SO; ``--so-seconds``);
* an ACTIVE task's ``next_*_at`` is re-armed from the new schedule.

An ``interval`` reconcile ("every N hours") has no wall-clock time to move and
is reported, never changed. Pure ``ac_entity_config`` writes - no schema, no
job, nothing pushed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .canonical.documents import (
    ENTITY_AR_OUTSTANDING,
    ENTITY_SALES_ORDER,
    is_document_entity,
)
from .canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from .models import (
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
)
from .services.etl_service import (
    DEFAULT_DOCUMENT_INCREMENTAL_MINUTES,
    DEFAULT_RECONCILE_TIMEZONE,
    RECONCILE_MODE_DAILY_AT,
    RECONCILE_MODE_INTERVAL,
    EtlService,
)

# The off-hours window, local MYT wall clock: the first reconcile starts at
# 02:00, the last one STARTS before 05:00.
WINDOW_START_MINUTES = 2 * 60
WINDOW_END_MINUTES = 5 * 60
MIN_SLOT_SPACING_MINUTES = 5
DEFAULT_SO_INCREMENTAL_SECONDS = 30


@dataclass
class TaskChange:
    config_id: str
    tenant_id: str
    company_id: str
    entity_type: str
    etl_status: str
    before: Dict[str, Any]
    after: Dict[str, Any]
    note: str = ""

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass
class TuningPlan:
    changes: List[TaskChange] = field(default_factory=list)
    interval_tasks: List[TaskChange] = field(default_factory=list)

    @property
    def pending(self) -> List[TaskChange]:
        return [c for c in self.changes if c.changed]


def _is_fast_document(entity_type: str) -> bool:
    return (
        is_document_entity(entity_type) and entity_type != ENTITY_AR_OUTSTANDING
    ) or entity_type == ENTITY_GOODS_RECEIVED_NOTE


def _has_watermark(source_config: Dict[str, Any]) -> bool:
    return bool(source_config.get("watermarkColumn") or source_config.get("watermarkField"))


def _schedule_view(source_config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incrementalMinutes": source_config.get("incrementalMinutes"),
        "incrementalSeconds": source_config.get("incrementalSeconds"),
        "reconcileMode": source_config.get("reconcileMode"),
        "reconcileAt": source_config.get("reconcileAt"),
        "reconcileTimezone": source_config.get("reconcileTimezone"),
    }


def _slot_spacing(count: int) -> int:
    if count <= 1:
        return MIN_SLOT_SPACING_MINUTES
    span = WINDOW_END_MINUTES - WINDOW_START_MINUTES
    raw = span // count
    return max(MIN_SLOT_SPACING_MINUTES, (raw // MIN_SLOT_SPACING_MINUTES) * MIN_SLOT_SPACING_MINUTES)


def _slot_time(index: int, spacing: int) -> str:
    span = WINDOW_END_MINUTES - WINDOW_START_MINUTES
    offset = (index * spacing) % span  # wraps (two per slot) past ~36 tasks
    minutes = WINDOW_START_MINUTES + offset
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def plan_off_hours_schedule(
    db: Session, *, so_seconds: Optional[int] = DEFAULT_SO_INCREMENTAL_SECONDS
) -> TuningPlan:
    """The change set, computed from the CURRENT rows - writes nothing.
    ``so_seconds`` = the sales_order seconds cadence (None/0 = leave SO on
    minutes)."""
    from .services.etl_service import (
        MAX_INCREMENTAL_SECONDS,
        MIN_INCREMENTAL_SECONDS,
        seconds_cadence_allowed,
    )
    from .scheduler import sweep_order_key

    if so_seconds and not MIN_INCREMENTAL_SECONDS <= so_seconds <= MAX_INCREMENTAL_SECONDS:
        raise ValueError(
            f"so_seconds must be {MIN_INCREMENTAL_SECONDS}-{MAX_INCREMENTAL_SECONDS} (or 0)."
        )

    rows = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.source_impl.in_((SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP)),
            AcEntityConfig.delivery_mode == DELIVERY_MODE_PUSH,
        )
        .all()
    )
    # Documents first (the CRM's working-day data must be reconciled long
    # before 08:00), then masters; inside each group the sweep's own order,
    # then a stable id order so a re-run assigns identical slots.
    rows.sort(
        key=lambda r: (
            0 if _is_fast_document(r.entity_type) else 1,
            sweep_order_key(r.entity_type),
            r.entity_type,
            r.tenant_id,
            r.company_id,
            r.id,
        )
    )
    plan = TuningPlan()
    daily = [
        r for r in rows
        if str((r.source_config or {}).get("reconcileMode") or RECONCILE_MODE_DAILY_AT)
        != RECONCILE_MODE_INTERVAL
    ]
    spacing = _slot_spacing(len(daily))
    slot_of = {row.id: _slot_time(i, spacing) for i, row in enumerate(daily)}

    for row in rows:
        config = dict(row.source_config or {})
        before = _schedule_view(config)
        after_config = dict(config)
        notes = []
        if row.id in slot_of:
            after_config["reconcileMode"] = RECONCILE_MODE_DAILY_AT
            after_config["reconcileAt"] = slot_of[row.id]
            after_config["reconcileTimezone"] = DEFAULT_RECONCILE_TIMEZONE
        if _is_fast_document(row.entity_type) and _has_watermark(config):
            current = config.get("incrementalMinutes")
            if not isinstance(current, int) or current > DEFAULT_DOCUMENT_INCREMENTAL_MINUTES:
                after_config["incrementalMinutes"] = DEFAULT_DOCUMENT_INCREMENTAL_MINUTES
            if (
                so_seconds
                and row.entity_type == ENTITY_SALES_ORDER
                and row.source_impl == SOURCE_IMPL_SQL_DB
                and config.get("watermarkColumn")
                and seconds_cadence_allowed(row.entity_type, has_watermark=True)
            ):
                after_config["incrementalSeconds"] = so_seconds
        elif _is_fast_document(row.entity_type):
            notes.append("no watermark: incremental left as is (5-minute floor)")
        change = TaskChange(
            config_id=row.id,
            tenant_id=row.tenant_id,
            company_id=row.company_id,
            entity_type=row.entity_type,
            etl_status=row.etl_status,
            before=before,
            after=_schedule_view(after_config),
            note="; ".join(notes),
        )
        if row.id in slot_of:
            plan.changes.append(change)
        else:
            change.note = "interval reconcile: no wall-clock time to move"
            plan.interval_tasks.append(change)
            if change.changed:
                plan.changes.append(change)
    return plan


def apply_off_hours_schedule(
    db: Session, plan: TuningPlan, *, now: Optional[datetime] = None
) -> int:
    """Write ``plan``'s pending changes; returns how many rows changed. A NEW
    ``source_config`` dict is assigned (an in-place JSON mutation is invisible
    to SQLAlchemy). An ACTIVE task is re-armed from its new schedule."""
    now = now or datetime.now(timezone.utc)
    changed = 0
    for change in plan.pending:
        row = db.get(AcEntityConfig, change.config_id)
        if row is None:
            continue
        config = dict(row.source_config or {})
        for key, value in change.after.items():
            if value != change.before.get(key):
                config[key] = value
        row.source_config = config
        if row.etl_status == ETL_STATUS_ACTIVE:
            # The SAME translation activate/resume use (an HTTP task's
            # watermark lives under ``watermarkField``).
            next_incremental, next_reconcile = EtlService.next_run_times(
                EtlService._schedule_source_config(row), now=now
            )
            row.next_incremental_at = next_incremental
            row.next_reconcile_at = next_reconcile
        changed += 1
    db.commit()
    return changed


def _cadence(view: Dict[str, Any]) -> str:
    if view.get("incrementalSeconds"):
        return f"{view['incrementalSeconds']} s"
    return f"{view.get('incrementalMinutes')} min"


def render_plan(plan: TuningPlan) -> str:
    """The dry-run table the owner reads before ``--apply``."""
    lines = [
        "entity_type | company_id | status | incremental | reconcile (before -> after)",
        "-" * 96,
    ]
    for c in plan.changes:
        b, a = c.before, c.after
        before_rc = f"{b['reconcileAt'] or '-'} {b['reconcileTimezone'] or 'UTC'}"
        after_rc = f"{a['reconcileAt'] or '-'} {a['reconcileTimezone'] or 'UTC'}"
        flag = "" if c.changed else "  (unchanged)"
        lines.append(
            f"{c.entity_type} | {c.company_id} | {c.etl_status} | "
            f"{_cadence(b)} -> {_cadence(a)} | "
            f"{before_rc} -> {after_rc}{flag}"
            + (f"  [{c.note}]" if c.note else "")
        )
    for c in plan.interval_tasks:
        if c not in plan.changes:
            lines.append(f"{c.entity_type} | {c.company_id} | {c.etl_status} | [{c.note}]")
    lines.append("")
    lines.append(f"{len(plan.pending)} task(s) would change.")
    return "\n".join(lines)
