"""The run executor (plan sprint-2/08 D1/D14/D16) - ONE topological walk.

``run_workflow`` executes a persisted run's snapshot node-by-node, writing a
``WorkflowRunNode`` trace; a node failure halts the run (downstream skipped),
and ``email.send`` "succeeds" at enqueue. ``debug_execute`` is the n8n
staleness loop: re-run only stale/uncached nodes up to a target, reusing cached
outputs for the rest.

Park / resume (plan sprint-4/31 S4, D-A5-6): an action may raise
``WorkflowPaused`` to SUSPEND its run at the current node. ``_walk`` is the one
walk both a first pass and a resume run through - the park snapshots the walk
state on ``workflow_runs.resume_state_json`` and ``resume_run`` re-enters it
through the EXISTING dispatch, so serialized runs keep their FIFO ordering and
Redis lease semantics unchanged.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.workflow import (
    NODE_FAILED,
    NODE_SKIPPED,
    NODE_SUCCESS,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
    RUN_SUCCESS,
    RUN_WAITING,
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
)
from app.workflow_engine.context import build_initial_context, render_field, set_node_output
from app.workflow_engine.parking import WorkflowPaused  # re-exported (plan 31 §5.6)
from app.workflow_engine.registry import get_action, matches_show_when
from app.workflow_engine.schemas import (
    WorkflowNodeModel,
    parse_definition,
    topo_order,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ctx_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload or {}
    actor = payload.get("actor") or {}
    ctx = build_initial_context(
        triggered_by=payload.get("triggeredBy", "manual"),
        actor_name=actor.get("name", ""),
        actor_email=actor.get("email", ""),
        actor_id=actor.get("id", ""),
        inputs=payload.get("input") or {},
    )
    workflow_test = payload.get("_workflowTest") or {}
    ctx["_workflow.sandboxOnly"] = workflow_test.get("sandboxOnly") is True
    # Event-trigger context (slice 09): record fields, action, changes, statuses.
    for key, value in (payload.get("recordFacts") or {}).items():
        # `record.email` → `trigger.record.email` (the picker's namespace).
        ctx[f"trigger.{key}"] = value
    if payload.get("recordId") is not None:
        ctx["trigger.record.id"] = payload["recordId"]
    if "action" in payload:
        ctx["trigger.action"] = payload.get("action")
    if payload.get("changedFields"):
        ctx["trigger.changedFields"] = payload["changedFields"]
    for field, delta in (payload.get("changes") or {}).items():
        ctx[f"trigger.changes.{field}.from"] = (delta or {}).get("from")
        ctx[f"trigger.changes.{field}.to"] = (delta or {}).get("to")
    if payload.get("fromStatus") is not None:
        ctx["trigger.fromStatus"] = payload["fromStatus"]
    if payload.get("toStatus") is not None:
        ctx["trigger.toStatus"] = payload["toStatus"]
    if payload.get("firedAt") is not None:
        ctx["trigger.firedAt"] = payload["firedAt"]
    # Form-submitted context (sprint-3/02): formId/submissionId + each answer as
    # `trigger.answers.<key>` (address → dotted answers.addr.city already, since
    # the answer value carries the nested object; repeater/file = JSON/key str).
    if payload.get("formId") is not None:
        ctx["trigger.formId"] = payload["formId"]
    if payload.get("submissionId") is not None:
        ctx["trigger.submissionId"] = payload["submissionId"]
    for key, value in (payload.get("answers") or {}).items():
        ctx[f"trigger.answers.{key}"] = value
    # Omnichannel inbound-message context (sprint-4/17).
    oc = payload.get("omnichannel")
    if oc:
        ctx["trigger.message.id"] = oc.get("messageId")
        ctx["trigger.message.text"] = oc.get("messageText")
        ctx["trigger.message.type"] = oc.get("messageType")
        ctx["trigger.message.mediaUrl"] = oc.get("mediaUrl")
        ctx["trigger.contact.id"] = oc.get("contactId")
        ctx["trigger.contact.name"] = oc.get("contactName")
        ctx["trigger.contact.phone"] = oc.get("contactPhone")
        ctx["trigger.channel.id"] = oc.get("channelId")
        ctx["trigger.channel.name"] = oc.get("channelName")
        ctx["trigger.conversationId"] = oc.get("conversationId")
        ctx["trigger.message.isFirstMessage"] = oc.get("isFirstMessage")
    # Registry-driven extra context (plan sprint-4/31, `TriggerDef.context_extra`)
    # - one nesting level, camelCase preserved, so a new registered trigger
    # never needs its own hardcoded block here (AC-WFP-07/08..14).
    for key, value in (payload.get("eventData") or {}).items():
        ctx[f"trigger.{key}"] = value
    return ctx


def resolve_correlation_key(doc: Any, ctx: Dict[str, Any]) -> Optional[str]:
    """Resolve the immutable definition's serialized key for this run.

    S1 deliberately keeps this as a context seam; S2 can snapshot the result
    on ``WorkflowRun`` when it adds keyed dispatch. Parallel definitions return
    ``None`` and retain their existing behavior.
    """
    from app.workflow_engine.serialization import CorrelationKeyUnresolved

    execution = getattr(doc, "execution", None)
    if execution is None or execution.mode != "serialized":
        return None
    resolved = render_field(execution.correlationKey, ctx).strip()
    if not resolved:
        raise CorrelationKeyUnresolved(
            "Serialized execution requires a non-empty Correlation key."
        )
    return resolved


def _stateful_agent(node: WorkflowNodeModel) -> bool:
    return node.type == "ai_agent.run" and any(
        isinstance(row, dict) and row.get("stateful") is True
        for row in (node.config.get("outputParams") or [])
    )


def _prepare_node_context(
    ctx: Dict[str, Any],
    run: WorkflowRun,
    node: WorkflowNodeModel,
    completed_stateful: set[str],
    *,
    force_agent_state_test: bool = False,
    can_park: bool = True,
) -> None:
    ctx["_workflow.runId"] = run.id
    ctx["_workflow.workflowId"] = run.workflow_id
    ctx["_workflow.isTest"] = run.is_test is True
    ctx["_workflow.nodeId"] = node.id
    ctx["_workflow.reachableStatefulAgentIds"] = sorted(completed_stateful)
    ctx["_workflow.agentStateNamespace"] = (
        "test"
        if force_agent_state_test or run.is_test is True or run.triggered_by == "manual"
        else "prod"
    )
    # False inside `debug_execute` (a partial, ephemeral re-run): a node that
    # would PARK the run has nothing to resume there, so it fails loudly with
    # its own message instead of stranding a module wait row that points at a
    # run which is not, and never will be, `waiting` (plan 31 S4).
    ctx["_workflow.canPark"] = can_park


def _execute_node(
    db: Session, tenant_id: str, node: WorkflowNodeModel, ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """Run one node, mutating ``ctx`` with its output. Trigger = seed only; IF
    evaluates its rule tree against the flat context → true/false."""
    if node.kind == "trigger":
        output = {
            "triggeredBy": ctx.get("trigger.triggeredBy", "manual"),
            **{k.split("trigger.input.")[1]: v for k, v in ctx.items() if k.startswith("trigger.input.")},
        }
        # Event triggers expose the captured event in their trace, not only in
        # the private flat executor context - registry-driven (plan 31 S3,
        # AC-WFP-38): every OTHER `trigger.<dotted>` context key is nested back
        # into JSON (`trigger.contact.id` -> `output["contact"]["id"]`), so a
        # NEW trigger's captured data (or a chained `workflow.trigger` run's
        # `source`/`parentRunId`/`contactId`) shows in Logs with no per-trigger
        # hardcoded block here - identical for production and synthetic test
        # events because both use the canonical envelope. `trigger.input.*`
        # stays flat (the pre-existing manual-trigger shape, above) and
        # `trigger.triggeredBy` is already surfaced. `trigger.record.*` is
        # SKIPPED - that is the rule-engine fact surface (already its own
        # picker group), a different namespace from "what the trigger fired
        # with", and some record facts (e.g. a date fact's `.daysSince`/
        # `.daysUntil`) are BOTH a leaf value and a parent of derived
        # sub-facts, which a bare dotted-key nest can't represent as JSON.
        for key, value in ctx.items():
            if (
                not key.startswith("trigger.")
                or key.startswith("trigger.input.")
                or key.startswith("trigger.record.")
                or key == "trigger.triggeredBy"
            ):
                continue
            parts = key.split(".")[1:]
            target = output
            collided = False
            for part in parts[:-1]:
                existing = target.get(part)
                if isinstance(existing, dict):
                    target = existing
                elif part not in target:
                    target = target.setdefault(part, {})
                else:
                    # Defense in depth: a scalar already claims this path.
                    # Never crash a run over a Logs-display nicety - drop
                    # only this one key.
                    collided = True
                    break
            if collided:
                continue
            leaf = parts[-1]
            if isinstance(target.get(leaf), dict):
                # Symmetric guard: a deeper key already nested a branch here
                # (processed earlier in iteration order) - never let a later
                # scalar silently clobber it. Drop only this one key.
                continue
            target[leaf] = value
        return output
    if node.kind == "if":
        from app.rule_engine.evaluator import evaluate

        # The condition tree's fact keys ARE the flat context's dotted keys
        # (trigger.record.*, trigger.actor.*, nodes.<id>.*) - pass ctx straight.
        passed = bool(evaluate(node.config.get("conditions"), ctx))
        output = {"passed": passed}
        set_node_output(ctx, node.id, output)
        return output
    action = get_action(node.type)
    if action is None:
        raise RuntimeError(f'Unknown action "{node.type}".')
    output = action.executor(db, tenant_id, node.config, ctx)
    set_node_output(ctx, node.id, output)
    return output


def _redact_config(config: Optional[Dict[str, Any]], action) -> Dict[str, Any]:
    """Deep-copy ``config`` masking every field the ``ActionDef`` flags
    ``redacted`` (plan sprint-4/31 review B1) - closes the LITERAL-secret gap
    the ``mergeable=False`` convention alone didn't (a header value typed as a
    literal, not a merge token, was still stored verbatim). A `keyValue`-shaped
    field (list of ``{key, value}`` rows) keeps its keys and masks each row's
    ``value``; any other shape masks the whole value. This runs BEFORE the raw
    config ever reaches ``input_json`` - the trace never carries the secret,
    not even transiently."""
    import copy

    out: Dict[str, Any] = copy.deepcopy(config or {})
    if action is None:
        return out
    for fld in action.fields:
        if not getattr(fld, "redacted", False):
            continue
        value = out.get(fld.key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict) and "value" in row:
                    row["value"] = "***"
        elif value is not None:
            out[fld.key] = "***"
    return out


def _node_input_json(node: WorkflowNodeModel, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The node's stored trace input: its raw ``config`` (with any ``redacted``
    field masked, B1) PLUS a ``resolved`` map of every mergeable field rendered
    against the run context, so Logs can show what was actually SENT (e.g. the
    message text), not just the template (user request, plan sprint-4/19).
    Non-mergeable fields (ids, selects) are never rendered - only
    substitution-only string fields are. Code nodes carry their own
    ``runtime.input`` and declare no mergeable field, so this adds nothing
    there."""
    if node.kind == "trigger":
        return None
    action = get_action(node.type)
    base: Dict[str, Any] = {"config": _redact_config(node.config, action)}
    if action is None:
        return base
    resolved: Dict[str, Any] = {}
    config = node.config or {}
    for fld in action.fields:
        if not fld.mergeable:
            continue
        # Respect show_when: a hidden field is not part of this run's input.
        if not matches_show_when(config, fld, action.fields):
            continue
        raw = config.get(fld.key)
        if isinstance(raw, str) and raw != "":
            try:
                resolved[fld.key] = render_field(raw, ctx)
            except Exception:  # noqa: BLE001 - a TRACE render must never fail the node
                continue
    if resolved:
        base["resolved"] = resolved
    return base


def _out_edges(doc) -> Dict[str, List]:
    edges: Dict[str, List] = {}
    for e in doc.edges:
        edges.setdefault(e.source, []).append((e.sourcePort or "out", e.target))
    return edges


def _taken_port(node: WorkflowNodeModel, output: Dict[str, Any]) -> Optional[str]:
    """The single port a BRANCHING node took, or ``None`` when the node fans out
    to every outgoing edge. The IF node's true/false is the original case; any
    ``ActionDef`` declaring ``ports`` generalizes it (D-A5-14) by returning a
    ``branch`` key - so Ask a question (answer/timeout) and Business hours
    (inside/outside) need no per-node special case in the walk."""
    if node.kind == "if":
        return "true" if (output or {}).get("passed") else "false"
    action = get_action(node.type)
    if action is not None and action.ports:
        return str((output or {}).get("branch") or "")
    return None


def _activate_targets(
    node: WorkflowNodeModel,
    output: Dict[str, Any],
    out_edges: Dict[str, List],
    active: set,
    taken_pred: Optional[Dict[str, List[str]]] = None,
) -> None:
    branch = _taken_port(node, output)
    for port, target in out_edges.get(node.id, []):
        if branch is not None and port != branch:
            continue
        active.add(target)
        if taken_pred is not None:
            taken_pred.setdefault(target, []).append(node.id)


def _walk(
    db: Session,
    run: WorkflowRun,
    doc,
    ctx: Dict[str, Any],
    active: set,
    start_index: int,
    completed_stateful: set,
    done_node_ids: Optional[set] = None,
) -> tuple[bool, Optional[int]]:
    """The ONE branch-aware active-set walk - shared by a first run AND a resume
    (plan sprint-4/31 S4). Returns ``(failed, paused_index)``: a non-None
    ``paused_index`` means the node at that position in the topological order
    raised :class:`WorkflowPaused` and the run must be parked there (downstream
    nodes are deliberately left with NO trace row - they have not been skipped,
    they have not happened yet).

    ``start_index``/``done_node_ids`` are the resume seam: nodes already carrying
    a terminal ``WorkflowRunNode`` row from an earlier pass are never re-executed
    and never get a second trace row."""
    ordered = topo_order(doc)
    out_edges = _out_edges(doc)
    done = done_node_ids or set()
    failed = False
    for index, node in enumerate(ordered):
        if index < start_index or node.id in done:
            continue
        _prepare_node_context(ctx, run, node, completed_stateful)
        rn = WorkflowRunNode(
            run_id=run.id, node_id=node.id, node_type=node.type, order_index=index
        )
        if failed or node.id not in active:
            rn.status = NODE_SKIPPED
            db.add(rn)
            continue
        rn.started_at = _now()
        try:
            rn.input_json = _node_input_json(node, ctx)
            output = _execute_node(db, run.tenant_id, node, ctx)
            rn.output_json = output
            rn.status = NODE_SUCCESS
            _activate_targets(node, output, out_edges, active)
            if _stateful_agent(node):
                completed_stateful.add(node.id)
        except WorkflowPaused as paused:
            # Control flow, never a failure: record the park on THIS node and
            # hand the suspension decision back to `run_workflow`.
            rn.output_json = {"parked": True, **paused.output}
            rn.status = NODE_SUCCESS
            rn.finished_at = _now()
            db.add(rn)
            return False, index
        except Exception as exc:  # noqa: BLE001 - a node failure halts the run (D14)
            rn.status = NODE_FAILED
            rn.error = str(exc)
            runtime = getattr(exc, "runtime", None)
            if isinstance(runtime, dict):
                # Keep the bounded console/termination of a failed Code
                # node inspectable (AC-SAR-67) without marking it "produced".
                rn.input_json = {**(rn.input_json or {}), "runtime": runtime}
            run.error = f"Node failed: {exc}"
            failed = True
        rn.finished_at = _now()
        db.add(rn)
    return failed, None


def _park_state(
    ctx: Dict[str, Any], active: set, completed_stateful: set, index: int
) -> Dict[str, Any]:
    """The JSON-safe snapshot of a suspended walk (plan 31 §5.6)."""
    from app.workflow_engine.entity_events import json_safe

    return {
        "ctx": json_safe(ctx),
        "active": sorted(active),
        "completedStateful": sorted(completed_stateful),
        "index": index,
    }


def run_workflow(db: Session, run_id: str) -> WorkflowRun:
    """Execute a persisted run end-to-end (the Celery task body, D1) - a first
    pass OR the continuation of a parked one, chosen by ``resume_state_json``.

    The walk is branch-aware (slice 09): a node runs only if reached via a TAKEN
    edge (``active`` set). An IF node - or any branching ``ActionDef`` -
    activates only its taken port's targets, so the untaken branch's descendants
    are skipped (descendant-based, not order-based). A node failure still halts
    the whole run (downstream skipped)."""
    from app.workflow_engine.entity_events import set_origin

    run = (
        db.query(WorkflowRun)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .filter(
            WorkflowRun.id == run_id,
            WorkflowRun.tenant_id == Workflow.tenant_id,
            WorkflowRun.status == RUN_PENDING,
        )
        # The claim is a status-guarded row lock: a duplicate wakeup finds no
        # Pending row and returns. Overtake protection is NOT this lock - an
        # action may commit mid-run and release it - it is the RUNNING row's
        # heartbeat: the serialized drain refuses to advance past a fresh one
        # (serialization._live_running_run_id) and the beat reaper fails a
        # stale one.
        .with_for_update()
        .first()
    )
    if run is None:
        existing = (
            db.query(WorkflowRun)
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
            .filter(
                WorkflowRun.id == run_id,
                WorkflowRun.tenant_id == Workflow.tenant_id,
            )
            .first()
        )
        if existing is None:
            raise RuntimeError(f"Run {run_id} not found.")
        # Duplicate Celery delivery or wakeup. A terminal/running run is never
        # executed again.
        return existing

    run.status = RUN_RUNNING
    started = _now()
    # A resumed run keeps its ORIGINAL start time (one run, one duration) -
    # only a first pass stamps it.
    if run.started_at is None:
        run.started_at = started
    run.heartbeat_at = started
    db.flush()

    # Tag the session so action writes during this run carry the loop chain (D5).
    # `set_origin` returns the PREVIOUS origin so it can be restored below -
    # nesting-safe: a `workflow.trigger` step dispatches a CHILD run on this
    # SAME session (eager dev), and an unconditional clear-on-exit would strip
    # the PARENT's origin off every event the parent emits after that node,
    # collapsing its loop-guard chain to empty (plan 31 S3 review B-3).
    prev_origin = set_origin(
        db, {"run_id": run.id, "workflow_id": run.workflow_id, "depth": run.depth or 0}
    )

    doc = parse_definition(run.definition_snapshot_json)
    # Resume (plan 31 S4): the parked walk's own snapshot replaces the fresh
    # trigger-payload context, so nodes that already ran keep their outputs and
    # the active set survives the suspension.
    resume_state = run.resume_state_json or None
    ctx = (
        dict(resume_state.get("ctx") or {})
        if resume_state
        else _ctx_from_payload(run.trigger_payload_json or {})
    )
    try:
        correlation_key = run.correlation_key
        if correlation_key is None:
            # Compatibility for a legacy/manual row created before S2. All
            # production creation paths snapshot before commit below.
            correlation_key = resolve_correlation_key(doc, ctx)
            if correlation_key is not None:
                from app.workflow_engine.serialization import correlation_digest

                run.correlation_key = correlation_key
                run.correlation_key_digest = correlation_digest(correlation_key)
    except RuntimeError as exc:
        run.status = RUN_FAILED
        run.error = str(exc)
        run.finished_at = _now()
        db.commit()
        set_origin(db, prev_origin)
        return run
    if correlation_key is not None:
        ctx["_workflow.correlationKey"] = correlation_key
    ordered = topo_order(doc)

    if resume_state:
        active = set(resume_state.get("active") or [])
        completed_stateful: set[str] = set(resume_state.get("completedStateful") or [])
        start_index = int(resume_state.get("index") or 0)
    else:
        # The trigger (root) is always active; everything else must be reached.
        active = {n.id for n in ordered if n.kind == "trigger"}
        completed_stateful = set()
        start_index = 0
    # A node that already carries a terminal trace row from an earlier pass is
    # never re-executed and never gets a second row (AC-WFP-42).
    done_node_ids = {
        rn.node_id
        for rn in run.nodes
        if rn.status in (NODE_SUCCESS, NODE_FAILED, NODE_SKIPPED)
    }
    # Structural set of stateful AI Agent node ids in the snapshot graph - the
    # read-state node validates against this (order-independent, unlike the
    # executed-this-pass reachableStatefulAgentIds the clear node uses).
    stateful_agent_ids = sorted(n.id for n in doc.nodes if _stateful_agent(n))
    ctx["_workflow.statefulAgentIds"] = stateful_agent_ids

    try:
        failed, paused_index = _walk(
            db, run, doc, ctx, active, start_index, completed_stateful, done_node_ids
        )
        if paused_index is not None:
            # Parked (AC-WFP-41): downstream nodes are NOT marked skipped, the
            # run leaves no lease behind (`waiting` is not `running`), and the
            # walk snapshot is what a later `resume_run` re-enters.
            run.status = RUN_WAITING
            run.paused_node_id = ordered[paused_index].id
            run.resume_state_json = _park_state(
                ctx, active, completed_stateful, paused_index
            )
        else:
            run.status = RUN_FAILED if failed else RUN_SUCCESS
            run.finished_at = _now()
            run.paused_node_id = None
            run.resume_state_json = None
        db.commit()
        db.refresh(run)
    finally:
        set_origin(db, prev_origin)
    return run


def resume_run(
    db: Session,
    run_id: str,
    tenant_id: str,
    *,
    node_id: str,
    output: Dict[str, Any],
    branch: Optional[str] = None,
) -> Optional[WorkflowRun]:
    """Continue a parked run from ``node_id`` with that node's final ``output``
    (plan sprint-4/31 S4, D-A5-6, AC-WFP-42).

    ``run_id`` is a polymorphic stored id (a module's wait row carries it) -
    the house rule (CLAUDE.md "Polymorphic stored ids") requires it be
    resolved tenant-scoped at use time, never with a bare id lookup, so
    ``tenant_id`` is REQUIRED (plan 31 review S1) even though no caller today
    passes a cross-tenant id - defence-in-depth against a planted/corrupt row.

    ``branch`` is the port the parked node took - required for a branching node
    (Ask a question: ``answer``/``timeout``), ``None`` for a single-out node
    (Wait). The run returns to ``pending`` and is re-dispatched through the
    EXISTING ``dispatch_persisted_run``, so a serialized definition keeps its
    FIFO ordering and its Redis lease semantics unchanged.

    Returns ``None`` (never raises) when the run is gone or is no longer parked
    at that node - a duplicate resume (two inbound messages, a sweep racing a
    reply) must be a silent no-op, not an error."""
    from app.workflow_engine.serialization import dispatch_persisted_run

    query = db.query(WorkflowRun).filter(
        WorkflowRun.id == run_id,
        WorkflowRun.tenant_id == tenant_id,
        WorkflowRun.status == RUN_WAITING,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    run = query.first()
    if run is None or run.paused_node_id != node_id:
        return None

    state = dict(run.resume_state_json or {})
    ctx: Dict[str, Any] = dict(state.get("ctx") or {})
    active = set(state.get("active") or [])
    completed_stateful = set(state.get("completedStateful") or [])
    index = int(state.get("index") or 0)

    doc = parse_definition(run.definition_snapshot_json)
    node = next((n for n in doc.nodes if n.id == node_id), None)
    if node is None:
        return None

    set_node_output(ctx, node_id, output)
    # Activate the taken port's targets - `_taken_port` reads the branching
    # node's `ports`, so a caller only has to say WHICH port it resumed on.
    _activate_targets(
        node, {**output, "branch": branch} if branch is not None else output,
        _out_edges(doc), active,
    )

    # The parked node's trace row already exists (written SUCCESS + parked at
    # suspension) - complete it in place rather than adding a second row.
    parked_row = (
        db.query(WorkflowRunNode)
        .filter(WorkflowRunNode.run_id == run.id, WorkflowRunNode.node_id == node_id)
        .first()
    )
    if parked_row is not None:
        parked_row.output_json = output
        parked_row.status = NODE_SUCCESS
        parked_row.finished_at = _now()
        db.add(parked_row)

    run.resume_state_json = _park_state(ctx, active, completed_stateful, index)
    run.paused_node_id = None
    run.status = RUN_PENDING
    run.error = None
    db.commit()
    db.refresh(run)
    dispatch_persisted_run(db, run)
    db.expire_all()
    return db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()


def debug_execute(
    db: Session,
    run: WorkflowRun,
    *,
    target_node_id: str,
    scratch: Dict[str, Dict[str, Any]],
    stale_node_ids: List[str],
) -> List[Dict[str, Any]]:
    """Staleness-aware partial re-run (D16, branch-aware since plan 10 D6).

    Walks the snapshot like ``run_workflow`` - a node runs only if reached via a
    TAKEN edge (``active`` set; an IF activates only its true OR false branch).
    Within the taken path, a node re-executes when it is (a) directly stale (an
    edited config - scratch edits are implicitly stale), (b) downstream of a node
    that re-ran this pass (staleness PROPAGATES along taken edges - a fresh
    upstream output invalidates every active descendant), (c) the target, or (d)
    never produced an output before. Otherwise its cached output is reused. Nodes
    on the UNTAKEN branch (or unreached) are left untouched - their stale cache
    never re-runs. Returns the touched nodes' results (ephemeral, not persisted).
    Real side effects fire (is_test); the caller commits."""
    doc = parse_definition(run.definition_snapshot_json)
    cache: Dict[str, Dict[str, Any]] = {
        rn.node_id: (rn.output_json or {}) for rn in run.nodes
    }
    # Nodes that genuinely produced an output last run (skipped/failed = none).
    produced = {rn.node_id for rn in run.nodes if rn.output_json is not None}
    ctx = _ctx_from_payload(run.trigger_payload_json or {})
    correlation_key = run.correlation_key or resolve_correlation_key(doc, ctx)
    if correlation_key is not None:
        ctx["_workflow.correlationKey"] = correlation_key
    ordered = topo_order(doc)

    # Apply scratch config edits to the working doc. The frontend sends the
    # CURRENT config of EVERY node as scratch, so a node is stale only when its
    # scratch config actually DIFFERS from the snapshot - never blanket-stale
    # every node (that would defeat the cache and re-fire side effects for the
    # whole chain). A genuine edit makes the node stale; it then propagates
    # downstream via ``recomputed``.
    stale = set(stale_node_ids)
    if scratch:
        for node in doc.nodes:
            if node.id in scratch:
                new_config = {**node.config, **scratch[node.id]}
                if new_config != node.config:
                    stale.add(node.id)
                node.config = new_config

    out_edges = _out_edges(doc)

    active = {n.id for n in ordered if n.kind == "trigger"}
    ctx["_workflow.statefulAgentIds"] = sorted(n.id for n in doc.nodes if _stateful_agent(n))
    taken_pred: Dict[str, List[str]] = {}  # node → predecessors reached via a taken edge
    recomputed: set = set()  # nodes whose output changed this pass

    touched: List[Dict[str, Any]] = []
    completed_stateful: set[str] = set()
    for node in ordered:
        _prepare_node_context(
            ctx, run, node, completed_stateful,
            force_agent_state_test=True,
            # A debug pass is ephemeral: there is nothing to resume, so a
            # parking node fails with its own message instead of stranding a
            # wait row (plan 31 S4).
            can_park=False,
        )
        is_target = node.id == target_node_id
        reached = node.id in active
        if not reached and not is_target:
            # Untaken branch / unreached and not the explicit target - leave it.
            continue
        upstream_dirty = any(p in recomputed for p in taken_pred.get(node.id, []))
        # The explicit target ALWAYS runs (n8n "execute this node" - even when
        # it sits on the currently-untaken branch); otherwise re-run only on a
        # genuine stale/dirty/never-produced reason and reuse the cache.
        must_run = (
            is_target
            or node.id in stale
            or upstream_dirty
            or node.id not in produced
        )
        if must_run:
            try:
                output = _execute_node(db, run.tenant_id, node, ctx)
            except Exception as exc:  # noqa: BLE001 - mirror run_workflow: a node
                # failure halts the pass here (D14), never a 500 (AC-ASR-11).
                runtime = getattr(exc, "runtime", None)
                input_json = _node_input_json(node, ctx)
                if isinstance(runtime, dict):
                    input_json = {**(input_json or {}), "runtime": runtime}
                touched.append(
                    {
                        "nodeId": node.id,
                        "nodeType": node.type,
                        "status": NODE_FAILED,
                        "inputJson": input_json,
                        "outputJson": None,
                        "error": str(exc),
                    }
                )
                break
            cache[node.id] = output
            recomputed.add(node.id)
            touched.append(
                {
                    "nodeId": node.id,
                    "nodeType": node.type,
                    "status": NODE_SUCCESS,
                    "inputJson": _node_input_json(node, ctx),
                    "outputJson": output,
                    "error": None,
                }
            )
        else:
            # Reuse the cached output - re-hydrate the context from it.
            output = cache[node.id]
            set_node_output(ctx, node.id, output)
        if reached and _stateful_agent(node):
            completed_stateful.add(node.id)
        if is_target:
            break
        # Activate the taken downstream edges (branch-aware, like run_workflow).
        # Only a node actually REACHED via a taken edge propagates activation -
        # a forced off-path target never fabricates a downstream walk.
        if reached:
            _activate_targets(node, output or {}, out_edges, active, taken_pred)
    return touched
