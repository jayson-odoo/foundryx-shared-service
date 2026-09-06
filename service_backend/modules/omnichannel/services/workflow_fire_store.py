"""Trigger-once-per-contact claim store (plan sprint-4/31, D-A5-4).

The module owns both the table (`WorkflowContactFire`) and the claim function;
core only calls the generic `TriggerDef.fire_guard(db, wf, config, ev)` seam
(`app/workflow_engine/entity_events.py::_match_and_enqueue`) - no core table,
no core knowledge of "contact". A SAVEPOINT (`Session.begin_nested`) scopes the
unique-constraint race to just this insert, so a losing claim never rolls back
sibling workflow runs already flushed in the SAME dispatch batch (multiple
candidate workflows for one event share one `Session`, see `entity_events.
_dispatch`).
"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import WorkflowContactFire


def claim_fire(db: Session, *, tenant_id: str, workflow_id: str, contact_id: str) -> bool:
    """Atomically claim (tenant, workflow, contact). Returns True on a WINNING
    claim (create the run), False when already claimed (skip - AC-WFP-15)."""
    try:
        with db.begin_nested():
            db.add(
                WorkflowContactFire(
                    tenant_id=tenant_id, workflow_id=workflow_id, contact_id=contact_id
                )
            )
            db.flush()
        return True
    except IntegrityError:
        return False


def delete_for_workflow(db: Session, tenant_id: str, workflow_id: str) -> None:
    """Delete every claim for a permanently-deleted workflow (AC-WFP-15 -
    markers are "deleted with the workflow"). Called by the `workflow`
    `deleted` domain-event subscriber registered in `workflow_nodes.py` -
    core emits that event already (`WorkflowService.remove`); no core edit."""
    db.query(WorkflowContactFire).filter(
        WorkflowContactFire.tenant_id == tenant_id,
        WorkflowContactFire.workflow_id == workflow_id,
    ).delete(synchronize_session=False)
