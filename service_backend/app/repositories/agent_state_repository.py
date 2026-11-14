"""Tenant-scoped persistence for stateful workflow Agent state."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowAgentState


class AgentStateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
    ) -> Optional[WorkflowAgentState]:
        return (
            self.db.query(WorkflowAgentState)
            .filter(
                WorkflowAgentState.tenant_id == tenant_id,
                WorkflowAgentState.workflow_id == workflow_id,
                WorkflowAgentState.node_id == node_id,
                WorkflowAgentState.correlation_key == correlation_key,
            )
            .first()
        )

    def add(self, state: WorkflowAgentState) -> WorkflowAgentState:
        self.db.add(state)
        self.db.flush()
        return state

    def save_initial(
        self,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
        state: dict,
        provenance: dict,
        *,
        pending_question: Optional[str] = None,
        pending_field: Optional[str] = None,
    ) -> WorkflowAgentState:
        row = WorkflowAgentState(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            node_id=node_id,
            correlation_key=correlation_key,
            state_json=state,
            provenance_json=provenance,
            pending_question=pending_question,
            pending_field=pending_field,
            revision=0,
        )
        return self.add(row)

    def compare_and_swap(
        self,
        row: WorkflowAgentState,
        *,
        expected_revision: int,
        state: dict,
        provenance: dict,
        pending_question: Optional[str],
        pending_field: Optional[str],
    ) -> bool:
        now = datetime.now(timezone.utc)
        updated = (
            self.db.query(WorkflowAgentState)
            .filter(
                WorkflowAgentState.id == row.id,
                WorkflowAgentState.tenant_id == row.tenant_id,
                WorkflowAgentState.workflow_id == row.workflow_id,
                WorkflowAgentState.node_id == row.node_id,
                WorkflowAgentState.correlation_key == row.correlation_key,
                WorkflowAgentState.revision == expected_revision,
            )
            .update(
                {
                    WorkflowAgentState.state_json: state,
                    WorkflowAgentState.provenance_json: provenance,
                    WorkflowAgentState.pending_question: pending_question,
                    WorkflowAgentState.pending_field: pending_field,
                    WorkflowAgentState.revision: expected_revision + 1,
                    WorkflowAgentState.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        self.db.flush()
        return updated == 1

    def clear(self, row: WorkflowAgentState, *, expected_revision: int) -> bool:
        return self.compare_and_swap(
            row,
            expected_revision=expected_revision,
            state={},
            provenance={},
            pending_question=None,
            pending_field=None,
        )

    def list_for_tenant(self, tenant_id: str):
        return (
            self.db.query(WorkflowAgentState)
            .filter(WorkflowAgentState.tenant_id == tenant_id)
            .all()
        )
