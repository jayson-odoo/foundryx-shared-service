"""CRUD event bus + after-commit dispatch (plan sprint-2/09 D1/D3/D4/D5).

A mutating service calls ``emit_entity_event`` which BUFFERS a domain event on
the Session (never acts on rolled-back data). A SQLAlchemy ``after_commit`` hook
drains the buffer → matches published workflows by the indexed denormalized
trigger columns (D4) → enqueues a run each. Rollback discards the buffer.

Loop guard (D5): every event captures its ORIGIN (the run whose action wrote
it, from ``db.info['workflow_origin']``). A workflow already in the originating
run chain never re-triggers (own write can't loop the same workflow), and a
global ``MAX_RUN_DEPTH`` kills cross-workflow cascades.
"""
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.workflow import (
    MAX_RUN_DEPTH,
    RUN_PENDING,
    TRIGGER_EVENT,
    Workflow,
    WorkflowRun,
)

logger = logging.getLogger("foundryx.workflows.events")

_BUFFER = "domain_events"
_DRAINING = "draining"
_ORIGIN = "workflow_origin"

# ── audit-log subscription seam (plan sprint-2/10 D5) ────────────────────────
# The emit → after-commit drain is the SINGLE point a future append-only
# audit_log (BL-084) hooks. A subscriber is called once per domain event, on a
# fresh post-commit session, with the full event dict (see ``emit_entity_event``
# for the stable shape: entity_type, action, tenant_id, record_id, actor,
# changes={field:{from,to}}, record_facts, extra, source). Each subscriber runs
# in its OWN commit, isolated - a failing/slow subscriber never breaks workflow
# dispatch or the triggering request. The audit log re-instruments nothing: it
# registers here at startup. This plan finalizes the seam; the log is its own
# future plan (retention / PII-redaction / tenant-scoped Resource UI).
_subscribers: List[Callable[[Session, Dict[str, Any]], None]] = []


def register_event_subscriber(fn: Callable[[Session, Dict[str, Any]], None]) -> None:
    """Register an after-commit consumer of every domain event. Idempotent."""
    if fn not in _subscribers:
        _subscribers.append(fn)


def unregister_event_subscriber(fn: Callable[[Session, Dict[str, Any]], None]) -> None:
    if fn in _subscribers:
        _subscribers.remove(fn)


def _notify_subscribers(session: Session, ev: Dict[str, Any]) -> None:
    """Fan an event out to registered subscribers - each in its own commit so
    one subscriber's failure is isolated from the next and from workflow dispatch."""
    for sub in _subscribers:
        try:
            sub(session, ev)
            session.commit()
        except Exception:  # noqa: BLE001 - a subscriber never breaks the seam
            logger.exception("event subscriber failed: %s", ev.get("entity_type"))
            session.rollback()


def _json_safe(value: Any) -> Any:
    """Coerce fact/change values to JSON-storable forms - the run payload is a
    JSON column, and record facts carry real datetimes/Decimals/enums."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def set_run_origin(db: Session, *, run_id: str, workflow_id: str, depth: int) -> None:
    """Tag the session so any entity event emitted while this run executes
    carries the originating chain (loop guard). Cleared by ``clear_run_origin``."""
    db.info[_ORIGIN] = {"run_id": run_id, "workflow_id": workflow_id, "depth": depth}


def clear_run_origin(db: Session) -> None:
    db.info.pop(_ORIGIN, None)


# Derived status (sprint-4/03 G7) - re-eval transitions tag their emitted events
# with this origin so the derived subscriber skips its OWN writes (loop-safe).
# It carries no run_id, so workflow dispatch sees an empty origin chain and a
# derived status change STILL triggers workflows (intended - a derived "Paid"
# can start a post-payment workflow).
DERIVED_ORIGIN = {"kind": "derived"}


def set_origin(
    db: Session, origin: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Set (or clear, with None) the session's event origin. Returns the
    previous value so a caller can restore it - nested-origin safe."""
    prev = db.info.get(_ORIGIN)
    if origin is None:
        db.info.pop(_ORIGIN, None)
    else:
        db.info[_ORIGIN] = origin
    return prev


def emit_entity_event(
    db: Session,
    entity_type: str,
    action: str,  # created | updated | deleted | status_changed
    record: Any,
    *,
    tenant_id: str,
    actor: Optional[Any] = None,
    actor_id: Optional[str] = None,
    changes: Optional[Dict[str, Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Buffer a domain event (drained on the next commit). Call AFTER the write
    is flushed, BEFORE the commit (so it rides the same transaction)."""
    from app.workflow_engine.entities import record_facts

    actor_dict: Optional[Dict[str, Any]] = None
    if actor is not None:
        actor_dict = {
            "id": getattr(actor, "id", None),
            "name": getattr(actor, "name", None) or getattr(actor, "email", "") or "",
            "email": getattr(actor, "email", "") or "",
        }
    elif actor_id:
        actor_dict = {"id": actor_id, "name": "", "email": ""}

    ev: Dict[str, Any] = {
        "entity_type": entity_type,
        "action": action,
        "tenant_id": tenant_id,
        "record_id": getattr(record, "id", None),
        "actor": actor_dict,
        "changes": _json_safe(changes) if changes else None,
        "extra": extra or {},
        "record_facts": _json_safe(record_facts(db, entity_type, record)),
        "source": db.info.get(_ORIGIN),
    }
    db.info.setdefault(_BUFFER, []).append(ev)


# ---- after-commit drain ----------------------------------------------------


def _dispatch(events: List[Dict[str, Any]], bind) -> None:
    """Match + enqueue a batch on a FRESH session bound to ``bind`` (the
    after-commit session is in 'committed' state and can't emit SQL). Child
    events (action writes that emit again) are looped in, loop-guarded."""
    disp = Session(bind=bind)
    disp.info[_DRAINING] = True  # disp's own run-commits won't spawn nested drains
    try:
        pending = list(events)
        while pending:
            ev = pending.pop(0)
            try:
                _match_and_enqueue(disp, ev)
                children = disp.info.pop(_BUFFER, [])
                disp.commit()
                pending.extend(children)
            except Exception:  # noqa: BLE001 - a bad event never breaks the request
                logger.exception("workflow event dispatch failed: %s", ev.get("entity_type"))
                disp.rollback()
                disp.info.pop(_BUFFER, None)
            # Audit-log seam (D5) - independent of workflow matching above.
            _notify_subscribers(disp, ev)
            # A subscriber may emit its own events (derived-status re-eval fires
            # status_changed transitions, sprint-4/03) - cascade them through the
            # SAME loop so they reach workflow matching too. Empty unless a
            # subscriber emitted, so a no-op for plain audit subscribers.
            pending.extend(disp.info.pop(_BUFFER, []))
    finally:
        disp.close()


def notify_entity_event(
    db: Session,
    entity_type: str,
    action: str,
    record: Any,
    *,
    tenant_id: str,
    actor: Optional[Any] = None,
    actor_id: Optional[str] = None,
    changes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """emit + drain - for services whose repository commits internally (call
    AFTER the successful write)."""
    emit_entity_event(
        db, entity_type, action, record,
        tenant_id=tenant_id, actor=actor, actor_id=actor_id, changes=changes,
    )
    dispatch_pending(db)


def dispatch_pending(db: Session) -> None:
    """Drain this session's buffer NOW (services whose repo commits internally
    emit AFTER a successful write, then call this - the data is committed, never
    rolled back, D3). Swallows everything - workflow dispatch is fire-and-forget
    relative to the triggering request."""
    events = db.info.pop(_BUFFER, None)
    if not events:
        return
    try:
        _dispatch(events, db.get_bind())
    except Exception:  # noqa: BLE001 - never propagate to the caller's request
        logger.exception("workflow dispatch failed")


def _drain(committed: Session) -> None:
    """``after_commit`` auto-drain (for emits that ride a service's own commit,
    e.g. status_machine)."""
    events = committed.info.pop(_BUFFER, None)
    if not events:
        return
    if committed.info.get(_DRAINING):
        # A nested commit inside an active drain - leave events for the owning loop.
        committed.info.setdefault(_BUFFER, []).extend(events)
        return
    try:
        _dispatch(events, committed.get_bind())
    except Exception:  # noqa: BLE001 - a broken workflow never breaks the emitter
        logger.exception("workflow drain failed")


def _discard(session: Session) -> None:
    session.info.pop(_BUFFER, None)


def _trigger_types_for(action: str) -> List[str]:
    if action == "created":
        return ["entity.created"]
    if action == "deleted":
        return ["entity.deleted"]
    if action == "updated":
        return ["entity.updated", "entity.field_changed"]
    if action == "status_changed":
        return ["entity.status_changed"]
    if action == "submitted":
        # Form-engine submission (plan sprint-3/02). The denormalized
        # trigger_entity_type is the constant "form_submission"; per-form
        # selectivity is refined by formId below.
        return ["form.submitted"]
    return []


def _published_trigger_config(session: Session, wf: Workflow) -> Dict[str, Any]:
    from app.models.workflow import WorkflowVersion

    version = (
        session.query(WorkflowVersion)
        .filter(WorkflowVersion.id == wf.current_version_id)
        .first()
    )
    if version is None:
        return {}
    for node in (version.definition_json or {}).get("nodes", []):
        if node.get("kind") == "trigger":
            return node.get("config") or {}
    return {}


def _passes_refine(config: Dict[str, Any], ev: Dict[str, Any], trigger_type: str) -> bool:
    """In-Python refinement the indexed query can't do (D4)."""
    from app.workflow_engine.entities import attr_for

    if trigger_type == "entity.field_changed":
        wanted = config.get("field")
        # The picker stores a camelCase field key; the emitted change-diff keys
        # are snake_case model attrs - compare in the canonical space.
        return bool(wanted) and attr_for(str(wanted)) in (ev.get("changes") or {})
    if trigger_type == "entity.status_changed":
        extra = ev.get("extra") or {}
        from_ok = not config.get("fromStatus") or config.get("fromStatus") == extra.get("from_status_id")
        to_ok = not config.get("toStatus") or config.get("toStatus") == extra.get("to_status_id")
        return from_ok and to_ok
    if trigger_type == "form.submitted":
        # Per-form selectivity: the picked formId must match the submitted form.
        wanted = config.get("formId")
        return bool(wanted) and wanted == (ev.get("extra") or {}).get("formId")
    return True


def _origin_chain(session: Session, source: Optional[Dict[str, Any]]):
    """(set of workflow_ids in the originating run chain, parent depth)."""
    if not source:
        return set(), -1
    chain = set()
    rid = source.get("run_id")
    while rid:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == rid).first()
        if run is None:
            break
        chain.add(run.workflow_id)
        rid = run.triggered_by_run_id
    return chain, int(source.get("depth", 0))


def _match_and_enqueue(session: Session, ev: Dict[str, Any]) -> None:
    types = _trigger_types_for(ev["action"])
    if not types:
        return
    candidates = (
        session.query(Workflow)
        .filter(
            Workflow.tenant_id == ev["tenant_id"],
            Workflow.is_active.is_(True),
            Workflow.is_trashed.is_(False),
            Workflow.current_version_id.isnot(None),
            Workflow.trigger_entity_type == ev["entity_type"],
            Workflow.trigger_type.in_(types),
        )
        .all()
    )
    if not candidates:
        return

    chain, parent_depth = _origin_chain(session, ev.get("source"))
    new_depth = parent_depth + 1

    for wf in candidates:
        config = _published_trigger_config(session, wf)
        if not _passes_refine(config, ev, wf.trigger_type):
            continue
        if wf.id in chain:
            continue  # own write / cycle - never re-trigger a workflow in the chain
        if new_depth > MAX_RUN_DEPTH:
            logger.warning("loop guard tripped: workflow %s at depth %s", wf.id, new_depth)
            continue
        _create_run(session, wf, ev, depth=new_depth)


def _create_run(session: Session, wf: Workflow, ev: Dict[str, Any], *, depth: int) -> None:
    from app.config import settings
    from app.models.workflow import WorkflowVersion

    version = (
        session.query(WorkflowVersion)
        .filter(WorkflowVersion.id == wf.current_version_id)
        .first()
    )
    if version is None:
        return
    actor = ev.get("actor") or {}
    extra = ev.get("extra") or {}
    payload = {
        "triggeredBy": TRIGGER_EVENT,
        "actor": actor,
        "action": ev["action"],
        "recordId": ev.get("record_id"),
        "changedFields": list((ev.get("changes") or {}).keys()),
        "changes": ev.get("changes") or {},
        "recordFacts": ev.get("record_facts") or {},
        "fromStatus": extra.get("from_status_id"),
        "toStatus": extra.get("to_status_id"),
    }
    # Form submission (sprint-3/02): flat trigger.formId/submissionId + the
    # answer map (executor flattens answers → trigger.answers.<key>).
    if ev["action"] == "submitted":
        payload["formId"] = extra.get("formId")
        payload["submissionId"] = extra.get("submissionId")
        payload["answers"] = extra.get("answers") or {}
    source = ev.get("source") or {}
    run = WorkflowRun(
        tenant_id=wf.tenant_id,
        workflow_id=wf.id,
        version_id=wf.current_version_id,
        version_number=version.version_number,
        status=RUN_PENDING,
        triggered_by=TRIGGER_EVENT,
        definition_snapshot_json=json.loads(json.dumps(version.definition_json)),
        trigger_payload_json=payload,
        triggered_by_run_id=source.get("run_id"),
        depth=depth,
        actor_id=actor.get("id"),
    )
    session.add(run)
    session.flush()
    run_id = run.id

    if settings.celery_task_always_eager:
        from app.workflow_engine.executor import run_workflow

        run_workflow(session, run_id)
    else:
        session.commit()
        from app.workflow_engine.worker import run_workflow_task

        run_workflow_task.delay(run_id)


# Register once on the Session class (all sessions share the hook).
event.listen(Session, "after_commit", _drain)
event.listen(Session, "after_rollback", _discard)
