"""`workflow.trigger` (plan sprint-4/31 S2, AC-WFP-33) - start another
PUBLISHED workflow of the SAME tenant, optionally carrying a contact id and a
merge-rendered JSON payload, from inside a running workflow.

Reuses the SAME `create_run_for_event` seam the CRUD event bus and
`WorkflowService.run_shortcut` both use (D-A3-10 precedent) - this file never
constructs a second `WorkflowRun(...)`. A CORE action (not omnichannel-owned):
the only omnichannel-specific bit is an optional, best-effort contact lookup
through the registered `omnichannel_contact` `WorkflowEntity` (generic,
guarded by the registry - core never imports the module directly).
"""
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.workflow_engine.context import render_field


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


def workflow_trigger(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    from app.models.workflow import MAX_RUN_DEPTH, Workflow, WorkflowRun
    from app.workflow_engine.entities import get_workflow_entity, load_record, record_facts
    from app.workflow_engine.entity_events import (
        CodeNotAuthorized,
        create_run_for_event,
        json_safe,
    )
    from app.workflow_engine.serialization import CorrelationKeyUnresolved

    target_id = str(config.get("workflowId") or "").strip()
    if not target_id:
        raise ActionError("Workflow is not configured.")

    parent_run_id = ctx.get("_workflow.runId")
    parent_workflow_id = ctx.get("_workflow.workflowId")
    # AC-WFP-33: self-trigger is refused at PUBLISH (422, schemas.py
    # definition_issues) - this is defense in depth for a manual/debug run of
    # a draft that was never re-published after an edit.
    if parent_workflow_id and target_id == parent_workflow_id:
        raise ActionError("A workflow cannot trigger itself.")

    # Same bar `WorkflowService.list_shortcuts`/`run_shortcut` hold a
    # triggerable workflow to (published + active + non-trashed, same tenant).
    wf = (
        db.query(Workflow)
        .filter(
            Workflow.id == target_id,
            Workflow.tenant_id == tenant_id,
            Workflow.is_active.is_(True),
            Workflow.is_trashed.is_(False),
            Workflow.current_version_id.isnot(None),
        )
        .first()
    )
    if wf is None:
        raise ActionError("Workflow not found, not published, or archived.")
    # "accept entity omnichannel_contact (or be entity-less)" - a workflow
    # bound to some OTHER entity (e.g. `form.submitted`) makes no sense as a
    # `workflow.trigger` target; a contact id in its context would be inert.
    if wf.trigger_entity_type not in (None, "omnichannel_contact"):
        raise ActionError("Target workflow must be a manual or contact-based workflow.")

    # `contactId` default = `trigger.record.id` (the generic entity-trigger
    # convention) when the author leaves it empty - the field is optional.
    contact_id = render_field(config.get("contactId"), ctx).strip()
    if not contact_id:
        contact_id = str(ctx.get("trigger.record.id") or "").strip()

    entity_type: Optional[str] = None
    record = None
    if contact_id:
        entity = get_workflow_entity("omnichannel_contact")
        if entity is not None:
            record = load_record(db, entity, tenant_id, contact_id)
            if record is None:
                raise ActionError("Contact not found.")
            entity_type = "omnichannel_contact"

    payload_raw = render_field(config.get("payload"), ctx).strip()
    extra_payload: Dict[str, Any] = {}
    if payload_raw:
        try:
            parsed = json.loads(payload_raw)
        except ValueError:
            extra_payload = {"raw": payload_raw}
        else:
            extra_payload = parsed if isinstance(parsed, dict) else {"value": parsed}

    # Depth threads off the CURRENT run row (the flat ctx has no depth key) so
    # a chain of `workflow.trigger` actions still hits the existing loop-guard
    # depth cap (D5 parity) - never a second unbounded chaining mechanism.
    current_depth = 0
    if parent_run_id:
        current_depth = (
            db.query(WorkflowRun.depth).filter(WorkflowRun.id == parent_run_id).scalar() or 0
        )
    new_depth = current_depth + 1
    if new_depth > MAX_RUN_DEPTH:
        raise ActionError("Workflow chain depth limit reached.")

    ev: Dict[str, Any] = {
        "entity_type": entity_type,
        "action": "workflow_triggered",
        "tenant_id": tenant_id,
        "record_id": contact_id or None,
        "actor": None,
        "changes": None,
        "extra": {},
        # Coerced like every other event producer: these land in the child
        # run's JSON `trigger_payload_json`, and a contact's date facts are
        # real datetimes (an uncoerced fact 500s the INSERT, plan 31 S4).
        "record_facts": json_safe(
            record_facts(db, entity_type, record) if entity_type and record is not None else {}
        ),
        "source": (
            {"run_id": parent_run_id, "workflow_id": parent_workflow_id, "depth": current_depth}
            if parent_run_id
            else None
        ),
    }

    try:
        run = create_run_for_event(
            db,
            wf,
            ev,
            depth=new_depth,
            extra_context={
                "source": "workflow",
                "parentRunId": parent_run_id,
                "contactId": contact_id or None,
                "payload": extra_payload,
            },
        )
    except CodeNotAuthorized as exc:
        raise ActionError(
            "Target workflow's published version is not authorized to run automatically."
        ) from exc
    except CorrelationKeyUnresolved as exc:
        raise ActionError(str(exc)) from exc
    if run is None:
        raise ActionError("Workflow not found, not published, or archived.")
    return {"runId": run.id, "workflowId": wf.id}
