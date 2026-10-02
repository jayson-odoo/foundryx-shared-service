"""Business rules around durable stateful AI Agent state."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.workflow import Workflow, WorkflowAgentState
from app.repositories.agent_state_repository import AgentStateRepository
from app.workflow_engine.agent_state import ReductionResult, reduce_agent_state


class AgentStateError(Exception):
    pass


class AgentStateConflict(AgentStateError):
    pass


class AgentStateService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AgentStateRepository(db)

    @staticmethod
    def namespace_key(
        correlation_key: str,
        *,
        is_test: bool = False,
        namespace: Optional[str] = None,
    ) -> str:
        selected = namespace or ("test" if is_test else "prod")
        if selected == "production":
            selected = "prod"
        if selected not in {"test", "prod"}:
            raise AgentStateError("Unknown Agent-state namespace.")
        return f"{selected}:{correlation_key}"

    @classmethod
    def _key_for_namespace(cls, correlation_key: str, namespace: Optional[str]) -> str:
        return cls.namespace_key(correlation_key, namespace=namespace)

    def _assert_workflow(self, tenant_id: str, workflow_id: str) -> None:
        exists = (
            self.db.query(Workflow.id)
            .filter(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
            .first()
        )
        if exists is None:
            raise AgentStateError("Workflow state scope is not available.")

    def load(
        self,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
        *,
        namespace: Optional[str] = None,
    ) -> Optional[WorkflowAgentState]:
        self._assert_workflow(tenant_id, workflow_id)
        return self.repo.get(
            tenant_id,
            workflow_id,
            node_id,
            self._key_for_namespace(correlation_key, namespace),
        )

    def save_initial(
        self,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
        state: Dict[str, Any],
        provenance: Dict[str, Any],
        *,
        pending_question: Optional[str] = None,
        pending_field: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> WorkflowAgentState:
        self._assert_workflow(tenant_id, workflow_id)
        return self.repo.save_initial(
            tenant_id,
            workflow_id,
            node_id,
            self._key_for_namespace(correlation_key, namespace),
            state,
            provenance,
            pending_question=pending_question,
            pending_field=pending_field,
        )

    def apply(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
        schema: Any,
        patches: Any,
        message: str,
        run_id: str,
        message_id: Optional[str],
        pending_question: Optional[str] = None,
        pending_field: Optional[str] = None,
        is_test: bool = False,
        namespace: Optional[str] = None,
    ) -> tuple[WorkflowAgentState, ReductionResult]:
        physical_key = self.namespace_key(correlation_key, is_test=is_test, namespace=namespace)
        self._assert_workflow(tenant_id, workflow_id)
        row = self.repo.get(tenant_id, workflow_id, node_id, physical_key)
        if row is None:
            try:
                with self.db.begin_nested():
                    row = self.repo.save_initial(
                        tenant_id,
                        workflow_id,
                        node_id,
                        physical_key,
                        {},
                        {},
                    )
            except IntegrityError:
                # Another worker may have created the first row for this key.
                # The savepoint rollback keeps the outer run transaction usable.
                row = self.repo.get(tenant_id, workflow_id, node_id, physical_key)
                if row is None:
                    raise AgentStateConflict("Agent state could not be initialized safely.") from None
        result = reduce_agent_state(
            row.state_json or {},
            row.provenance_json or {},
            patches,
            message,
            schema,
            run_id=run_id,
            message_id=message_id,
            now=datetime.now(timezone.utc),
        )
        if result.changed_fields and pending_field in result.changed_fields:
            pending_question = None
            pending_field = None
        if pending_field is None:
            pending_question = None
        elif not isinstance(pending_question, str) or not pending_question.strip():
            # A pending target without its exact question is not an atomic
            # clarification and must never be persisted.
            pending_question = None
            pending_field = None
        if pending_field is not None:
            definitions = {
                item.get("key"): item
                for item in (schema if isinstance(schema, list) else [])
                if isinstance(item, dict)
            }
            if pending_field not in definitions or definitions[pending_field].get("stateful") is not True:
                pending_question = None
                pending_field = None
        if not self.repo.compare_and_swap(
            row,
            expected_revision=row.revision,
            state=result.state,
            provenance=result.provenance,
            pending_question=pending_question,
            pending_field=pending_field,
        ):
            raise AgentStateConflict("Agent state changed while this run was executing.")
        self.db.refresh(row)
        return row, result

    def clear(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        node_id: str,
        correlation_key: str,
        is_test: bool = False,
        namespace: Optional[str] = None,
    ) -> tuple[bool, Optional[int]]:
        physical_key = self.namespace_key(correlation_key, is_test=is_test, namespace=namespace)
        self._assert_workflow(tenant_id, workflow_id)
        row = self.repo.get(tenant_id, workflow_id, node_id, physical_key)
        if row is None:
            return False, None
        # Repository CAS uses a bulk UPDATE; refresh this identity-mapped row
        # before deciding whether a repeated clear is already a no-op.
        self.db.refresh(row)
        if (
            not (row.state_json or {})
            and not (row.provenance_json or {})
            and row.pending_question is None
            and row.pending_field is None
        ):
            return False, None
        previous = row.revision
        if not self.repo.clear(row, expected_revision=previous):
            raise AgentStateConflict("Agent state changed while it was being cleared.")
        return True, previous
