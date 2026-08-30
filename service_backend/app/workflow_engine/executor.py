"""The run executor (plan sprint-2/08 D1/D14/D16) - ONE topological walk.

``run_workflow`` executes a persisted run's snapshot node-by-node, writing a
``WorkflowRunNode`` trace; a node failure halts the run (downstream skipped),
and ``email.send`` "succeeds" at enqueue. ``debug_execute`` is the n8n
staleness loop: re-run only stale/uncached nodes up to a target, reusing cached
outputs for the rest.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.workflow import (
    NODE_FAILED,
    NODE_SKIPPED,
    NODE_SUCCESS,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_SUCCESS,
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
)
from app.workflow_engine.context import build_initial_context, render_field, set_node_output
from app.workflow_engine.registry import get_action
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
    return ctx


def resolve_correlation_key(doc: Any, ctx: Dict[str, Any]) -> Optional[str]:
    """Resolve the immutable definition's serialized key for this run.

    S1 deliberately keeps this as a context seam; S2 can snapshot the result
    on ``WorkflowRun`` when it adds keyed dispatch. Parallel definitions return
    ``None`` and retain their existing behavior.
    """
    execution = getattr(doc, "execution", None)
    if execution is None or execution.mode != "serialized":
        return None
    resolved = render_field(execution.correlationKey, ctx).strip()
    if not resolved:
        raise RuntimeError("Serialized execution requires a non-empty Correlation key.")
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
        # the private flat executor context. This is identical for production
        # and synthetic test events because both use the canonical envelope.
        if "trigger.message.id" in ctx:
            output["message"] = {
                "id": ctx.get("trigger.message.id"),
                "text": ctx.get("trigger.message.text"),
                "type": ctx.get("trigger.message.type"),
                "mediaUrl": ctx.get("trigger.message.mediaUrl"),
            }
            output["contact"] = {
                "id": ctx.get("trigger.contact.id"),
                "name": ctx.get("trigger.contact.name"),
                "phone": ctx.get("trigger.contact.phone"),
            }
            output["channel"] = {
                "id": ctx.get("trigger.channel.id"),
                "name": ctx.get("trigger.channel.name"),
            }
            output["conversationId"] = ctx.get("trigger.conversationId")
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


def run_workflow(db: Session, run_id: str) -> WorkflowRun:
    """Execute a persisted run end-to-end (the Celery task body, D1).

    The walk is branch-aware (slice 09): a node runs only if reached via a TAKEN
    edge (``active`` set). An IF node activates only its true OR false targets,
    so the untaken branch's descendants are skipped (descendant-based, not
    order-based). A node failure still halts the whole run (downstream skipped)."""
    from app.workflow_engine.entity_events import clear_run_origin, set_run_origin

    run = (
        db.query(WorkflowRun)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .filter(
            WorkflowRun.id == run_id,
            WorkflowRun.tenant_id == Workflow.tenant_id,
        )
        .first()
    )
    if run is None:
        raise RuntimeError(f"Run {run_id} not found.")

    run.status = RUN_RUNNING
    run.started_at = _now()
    db.flush()

    # Tag the session so action writes during this run carry the loop chain (D5).
    set_run_origin(db, run_id=run.id, workflow_id=run.workflow_id, depth=run.depth or 0)

    doc = parse_definition(run.definition_snapshot_json)
    ctx = _ctx_from_payload(run.trigger_payload_json or {})
    try:
        correlation_key = resolve_correlation_key(doc, ctx)
    except RuntimeError as exc:
        run.status = RUN_FAILED
        run.error = str(exc)
        run.finished_at = _now()
        db.commit()
        clear_run_origin(db)
        return run
    if correlation_key is not None:
        ctx["_workflow.correlationKey"] = correlation_key
    ordered = topo_order(doc)

    out_edges: Dict[str, List] = {}
    for e in doc.edges:
        out_edges.setdefault(e.source, []).append((e.sourcePort or "out", e.target))

    # The trigger (root) is always active; everything else must be reached.
    active = {n.id for n in ordered if n.kind == "trigger"}

    failed = False
    completed_stateful: set[str] = set()
    try:
        for index, node in enumerate(ordered):
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
                rn.input_json = {"config": node.config} if node.kind != "trigger" else None
                output = _execute_node(db, run.tenant_id, node, ctx)
                rn.output_json = output
                rn.status = NODE_SUCCESS
                # Activate the taken downstream edges.
                if node.kind == "if":
                    branch = "true" if output.get("passed") else "false"
                    for port, target in out_edges.get(node.id, []):
                        if port == branch:
                            active.add(target)
                else:
                    for _port, target in out_edges.get(node.id, []):
                        active.add(target)
                if _stateful_agent(node):
                    completed_stateful.add(node.id)
            except Exception as exc:  # noqa: BLE001 - a node failure halts the run (D14)
                rn.status = NODE_FAILED
                rn.error = str(exc)
                run.error = f"Node failed: {exc}"
                failed = True
            rn.finished_at = _now()
            db.add(rn)

        run.status = RUN_FAILED if failed else RUN_SUCCESS
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
    finally:
        clear_run_origin(db)
    return run


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
    correlation_key = resolve_correlation_key(doc, ctx)
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

    out_edges: Dict[str, List] = {}
    for e in doc.edges:
        out_edges.setdefault(e.source, []).append((e.sourcePort or "out", e.target))

    active = {n.id for n in ordered if n.kind == "trigger"}
    taken_pred: Dict[str, List[str]] = {}  # node → predecessors reached via a taken edge
    recomputed: set = set()  # nodes whose output changed this pass

    touched: List[Dict[str, Any]] = []
    completed_stateful: set[str] = set()
    for node in ordered:
        _prepare_node_context(
            ctx, run, node, completed_stateful, force_agent_state_test=True
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
            output = _execute_node(db, run.tenant_id, node, ctx)
            cache[node.id] = output
            recomputed.add(node.id)
            touched.append(
                {
                    "nodeId": node.id,
                    "nodeType": node.type,
                    "status": NODE_SUCCESS,
                    "inputJson": {"config": node.config} if node.kind != "trigger" else None,
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
            if node.kind == "if":
                branch = "true" if (output or {}).get("passed") else "false"
                for port, target in out_edges.get(node.id, []):
                    if port == branch:
                        active.add(target)
                        taken_pred.setdefault(target, []).append(node.id)
            else:
                for _port, target in out_edges.get(node.id, []):
                    active.add(target)
                    taken_pred.setdefault(target, []).append(node.id)
    return touched
