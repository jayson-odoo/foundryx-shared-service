"""Workflow actions for explicit Agent-state lifecycle transitions (clear) and
the read-only inspection node (plan sprint-4/20)."""
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.agent_state_service import AgentStateService


class ActionError(Exception):
    pass


def clear_agent_state(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    node_id = config.get("agentNodeId")
    workflow_id = ctx.get("_workflow.workflowId")
    correlation_key = ctx.get("_workflow.correlationKey")
    if not node_id or not workflow_id or not isinstance(correlation_key, str) or not correlation_key.strip():
        raise ActionError("Clear Agent State requires the current workflow Correlation key.")
    state_namespace = ctx.get("_workflow.agentStateNamespace") or (
        "test" if ctx.get("_workflow.isTest") is True else "prod"
    )
    allowed = ctx.get("_workflow.reachableStatefulAgentIds")
    if not isinstance(allowed, list) or node_id not in allowed:
        raise ActionError("The selected AI Agent is not reachable before this action.")
    cleared, previous = AgentStateService(db).clear(
        tenant_id=tenant_id,
        workflow_id=str(workflow_id),
        node_id=str(node_id),
        correlation_key=correlation_key,
        namespace=state_namespace,
    )
    return {"cleared": cleared, "previousRevision": previous}


def read_agent_state(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """READ-ONLY: load the accepted Agent state for the run's Correlation key
    and flatten it to outputs. Never writes - the AI Agent reducer stays the
    sole validated writer (plan 19 line 29 / plan 20 D3)."""
    node_id = config.get("agentNodeId")
    workflow_id = ctx.get("_workflow.workflowId")
    correlation_key = ctx.get("_workflow.correlationKey")
    if not node_id or not workflow_id or not isinstance(correlation_key, str) or not correlation_key.strip():
        raise ActionError("Read Agent State requires the current workflow Correlation key.")
    # Structural guard (plan 20 D4): the target must be a stateful AI Agent in
    # THIS workflow's graph. Order-independent - a read does not require the
    # agent to have executed on this run.
    allowed = ctx.get("_workflow.statefulAgentIds")
    if not isinstance(allowed, list) or node_id not in allowed:
        raise ActionError("The selected AI Agent is not part of this workflow.")
    state_namespace = ctx.get("_workflow.agentStateNamespace") or (
        "test" if ctx.get("_workflow.isTest") is True else "prod"
    )
    row = AgentStateService(db).load(
        tenant_id,
        str(workflow_id),
        str(node_id),
        correlation_key,
        namespace=state_namespace,
    )
    fields = dict(row.state_json) if row and isinstance(row.state_json, dict) else {}
    # Reserved diagnostics win over a same-named accepted field (same collision
    # convention as the plan-19 AI Agent diagnostics).
    return {
        **fields,
        "stateRevision": row.revision if row else 0,
        "pendingField": row.pending_field if row else None,
        "exists": row is not None,
    }


__all__ = ["ActionError", "clear_agent_state", "read_agent_state"]
