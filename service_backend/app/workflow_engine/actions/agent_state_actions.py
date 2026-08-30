"""Workflow actions for explicit state lifecycle transitions."""
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


__all__ = ["ActionError", "clear_agent_state"]
