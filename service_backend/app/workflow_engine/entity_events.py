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


def build_shortcut_event(
    db: Session, entity_type: str, record: Any, *, tenant_id: str, actor: Optional[Any]
) -> Dict[str, Any]:
    """Build the event-bus envelope for a shortcut run (plan sprint-4/27,
    D-A3-10) - the SAME shape ``emit_entity_event`` buffers below, so it flows
    through ``create_run_for_event``/``build_event_trigger_payload`` unchanged
    (the executor's `trigger.record.*`/`trigger.action`/`trigger.actor.*`
    flattening needs no shortcut-specific branch). A shortcut has no prior run
    chain (``source=None``) - it is always a fresh, top-level run, never a
    cascade; ``actor`` is the REAL actor (real admin under impersonation, D5.6)
    for attribution, matching every other ``actor_dict`` build in this module."""
    from app.workflow_engine.entities import record_facts

    actor_dict: Optional[Dict[str, Any]] = None
    if actor is not None:
        actor_dict = {
            "id": getattr(actor, "id", None),
            "name": getattr(actor, "name", None) or getattr(actor, "email", "") or "",
            "email": getattr(actor, "email", "") or "",
        }
    return {
        "entity_type": entity_type,
        "action": "shortcut",
        "tenant_id": tenant_id,
        "record_id": getattr(record, "id", None),
        "actor": actor_dict,
        "changes": None,
        "extra": {},
        "record_facts": _json_safe(record_facts(db, entity_type, record)),
        "source": None,
    }


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
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """emit + drain - for services whose repository commits internally (call
    AFTER the successful write)."""
    emit_entity_event(
        db, entity_type, action, record,
        tenant_id=tenant_id, actor=actor, actor_id=actor_id, changes=changes, extra=extra,
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


# The core CRUD event bus's fixed action->type mapping (plan sprint-2/09) -
# this stays hardcoded (it IS the core entity bus, not a registry item).
# Every OTHER action (form.submitted, omnichannel.*, ...) resolves from the
# registry via `TriggerDef.event_action` (plan sprint-4/31, closes A4's F3) -
# a newly registered module trigger needs NO further edit here (AC-WFP-07).
_CORE_ACTION_TRIGGER_TYPES: Dict[str, List[str]] = {
    "created": ["entity.created"],
    "deleted": ["entity.deleted"],
    "updated": ["entity.updated", "entity.field_changed"],
    "status_changed": ["entity.status_changed"],
}


def _trigger_types_for(action: str) -> List[str]:
    from app.workflow_engine.registry import list_triggers

    types = list(_CORE_ACTION_TRIGGER_TYPES.get(action, []))
    for trig in list_triggers():
        if trig.event_action == action and trig.key not in types:
            types.append(trig.key)
    return types


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
    """In-Python refinement the indexed query can't do (D4) - registry-driven
    (plan sprint-4/31, closes A4's F3): delegates to the matched TriggerDef's
    own ``refine`` callable. A trigger with no ``refine`` always passes (the
    old behaviour for `entity.created`/`entity.deleted`/`manual`/... )."""
    from app.workflow_engine.registry import get_trigger

    trig = get_trigger(trigger_type)
    if trig is None or trig.refine is None:
        return True
    return trig.refine(config, ev)


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
    from app.workflow_engine.registry import get_trigger

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
        trig_def = get_trigger(wf.trigger_type)
        if trig_def is not None and trig_def.fire_guard is not None:
            # "Trigger once per contact" (D-A5-4, AC-WFP-15) - a module-owned
            # atomic claim. A losing race (concurrent duplicate) skips this
            # candidate silently, never surfacing as a request error.
            if not trig_def.fire_guard(session, wf, config, ev):
                continue
        _create_run(session, wf, ev, depth=new_depth)


def build_event_trigger_payload(
    ev: Dict[str, Any],
    *,
    trigger_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Canonical event envelope consumed by the executor.

    Production dispatch and module-owned synthetic test builders share this
    function so their ``trigger.*`` context cannot drift.

    ``trigger_type``/``config`` (plan sprint-4/31, optional - callers that
    omit them get the unchanged base payload) let a registry-driven trigger
    contribute EXTRA ``trigger.*`` context via ``TriggerDef.context_extra``
    without a per-trigger hardcoded branch here - the executor flattens the
    result generically (``payload["eventData"]``, one nesting level).

    ``extra_context`` (plan sprint-4/31 S2, `workflow.trigger`) is a SECOND,
    caller-supplied source of ``eventData`` - merged over whatever the
    matched trigger's own ``context_extra`` produced (caller wins on a key
    collision). Lets a direct `create_run_for_event` caller that is NOT the
    CRUD event bus (a `workflow.trigger` action force-starting an unrelated
    workflow) inject its own ``trigger.source``/``trigger.parentRunId``/
    ``trigger.contactId``/``trigger.payload`` without teaching every
    registered trigger's `context_extra` about a chaining concept it has
    nothing to do with.
    """
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
    if ev["action"] == "received":
        # Omnichannel inbound message (sprint-4/17) - the executor flattens
        # this into trigger.message.*/trigger.contact.*/trigger.channel.*.
        payload["omnichannel"] = extra
    if trigger_type is not None:
        from app.workflow_engine.registry import get_trigger

        trig_def = get_trigger(trigger_type)
        if trig_def is not None and trig_def.context_extra is not None:
            payload["eventData"] = trig_def.context_extra(config or {}, ev)
    if extra_context:
        payload["eventData"] = {**(payload.get("eventData") or {}), **extra_context}
    return payload


class CodeNotAuthorized(Exception):
    """Raised by ``create_run_for_event`` when the published version carries
    Code nodes without a ``code_authorized_by`` stamp (fail closed, AC-SAR-68 /
    plan sprint-4/27 AC-IVE-38). No run is created."""


def create_run_for_event(
    session: Session,
    wf: Workflow,
    ev: Dict[str, Any],
    *,
    depth: int,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Optional[WorkflowRun]:
    """Create + persist + dispatch a ``WorkflowRun`` against ``wf``'s PUBLISHED
    version for a domain event ``ev`` (the event-bus envelope this module
    already builds via ``build_event_trigger_payload``).

    Extracted (plan sprint-4/27, D-A3-10) so the CRUD event bus
    (``_match_and_enqueue`` below) and the omnichannel-shortcut run path
    (``WorkflowService.run_shortcut``) share ONE code path - both inherit the
    same fail-closed Code-node authorization gate, correlation-key assignment
    (``assign_run_correlation``) and serialized dispatch
    (``dispatch_persisted_run``) for free, instead of a second run-construction
    site that could silently drift from the bus's guarantees.

    Returns ``None`` if the workflow's published version can no longer be
    resolved (defensive - the row raced a concurrent unpublish/delete).
    Raises ``CodeNotAuthorized`` - never silently skips - so a caller that
    needs to surface a 409 (the shortcut route) can distinguish it from the
    other None case; the bus path (below) catches it and logs, preserving its
    original fire-and-forget behavior.
    """
    from app.config import settings
    from app.models.workflow import WorkflowVersion

    version = (
        session.query(WorkflowVersion)
        .filter(
            WorkflowVersion.id == wf.current_version_id,
            WorkflowVersion.workflow_id == wf.id,
        )
        .first()
    )
    if version is None:
        return None
    from app.workflow_engine.schemas import has_code_nodes

    if has_code_nodes(version.definition_json) and not version.code_authorized_by:
        # Automated/shortcut triggers may execute a Code-bearing version ONLY
        # when a permitted actor stamped it at publish (AC-SAR-68). Fail closed.
        raise CodeNotAuthorized()
    trigger_config = _published_trigger_config(session, wf)
    payload = build_event_trigger_payload(
        ev, trigger_type=wf.trigger_type, config=trigger_config, extra_context=extra_context
    )
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
        actor_id=(ev.get("actor") or {}).get("id"),
    )
    from app.workflow_engine.serialization import (
        assign_run_correlation,
        dispatch_persisted_run,
    )

    assign_run_correlation(run)
    session.add(run)
    session.flush()

    if settings.celery_task_always_eager:
        # Eager mode IS execution (inline, on this session) - a run row here
        # has not been separately committed durable, so an executor crash
        # must propagate: swallowing it would let `run_shortcut` hand back a
        # `runId` for a row whose transaction then rolls back, and tests/dev
        # would silently lose real executor failures.
        dispatch_persisted_run(session, run)
        return run

    session.commit()
    try:
        dispatch_persisted_run(session, run)
    except Exception:  # noqa: BLE001 - B4 (round-3 codex triage): the run row
        # is ALREADY COMMITTED durable Pending by this point (non-eager path)
        # - a broker-down `.delay()` (or any dispatch-side error) must not
        # propagate: the shortcut route has no try/except for it and would
        # 500 while leaving the committed run stranded, and a client retry
        # would then create a SECOND run for the same click. Leave the run
        # Pending - it stays Pending for manual re-dispatch; no automatic
        # redrive exists for un-correlated runs (BL-SS-078) - log, and return
        # the already-created run untouched, never re-raise, never delete it.
        logger.exception(
            "workflow %s: dispatch failed for run %s; run stays Pending", wf.id, run.id
        )
    return run


def _create_run(session: Session, wf: Workflow, ev: Dict[str, Any], *, depth: int) -> None:
    try:
        create_run_for_event(session, wf, ev, depth=depth)
    except CodeNotAuthorized:
        logger.warning("workflow %s: Code-bearing version lacks authorization; skipped", wf.id)


# Register once on the Session class (all sessions share the hook).
event.listen(Session, "after_commit", _drain)
event.listen(Session, "after_rollback", _discard)
