"""Entity actions (plan sprint-2/09 D8) - move a record's status through its
state machine, or patch whitelisted fields. Both act as the synthetic Workflow
actor (authorized at publish, D10); every load is tenant-scoped. Their writes
emit ``entity.updated`` / ``status_changed`` domain events → loop-guarded by the
originating run chain (D5). The run owns the transaction (``commit=False``).
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.workflow_engine.context import render_field
from app.workflow_engine.entities import attr_for, get_workflow_entity, load_record


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


def _resolve_record(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]):
    entity_type = config.get("entityType")
    entity = get_workflow_entity(str(entity_type or ""))
    if entity is None:
        raise ActionError(f'Unknown entity "{entity_type}".')
    record_id = render_field(config.get("recordId"), ctx).strip()
    if not record_id:
        raise ActionError("Record id is empty after merging.")
    record = load_record(db, entity, tenant_id, record_id)
    if record is None:
        raise ActionError(f'{entity.label} "{record_id}" not found in this tenant.')
    return entity, record


def entity_transition_status(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.status_machine import StatusMachineError, transition

    entity, record = _resolve_record(db, tenant_id, config, ctx)
    if not entity.has_status:
        raise ActionError(f"{entity.label} has no state machine.")
    to_status_id = str(config.get("toStatus") or "")
    if not to_status_id:
        raise ActionError("No target status configured.")
    try:
        # Synthetic Workflow actor (None = system); the run owns the commit.
        transition(db, entity.entity_type, record, to_status_id, actor=None, tenant_id=tenant_id, commit=False)
    except StatusMachineError as exc:
        raise ActionError(str(exc)) from exc
    return {"status": to_status_id, "recordId": getattr(record, "id", None)}


def entity_update(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.workflow_engine.entity_events import emit_entity_event

    entity, record = _resolve_record(db, tenant_id, config, ctx)
    assignments = config.get("assignments") or []
    pending: Dict[str, str] = {}
    for row in assignments:
        if not isinstance(row, dict):
            continue
        # The UI sends camelCase field keys; the whitelist + the column are
        # snake_case - normalize to the ONE canonical attr (the guard must
        # compare what the producer emits, not an incidentally-equal form).
        attr = attr_for(str(row.get("field") or ""))
        if attr not in entity.writable:
            raise ActionError(f'Field "{attr}" is not writable on {entity.label}.')
        pending[attr] = render_field(row.get("value"), ctx)

    if not pending:
        return {"recordId": getattr(record, "id", None)}

    # B11 (plan-25 round-3 codex triage): an entity with its own validated
    # write path (type coercion, normalization, realtime/webhook fan-out)
    # routes through it INSTEAD OF the raw setattr loop below, so a workflow
    # write can't silently skip every other writer's side effects.
    if entity.apply_update is not None:
        try:
            entity.apply_update(db, record, pending, None)
        except ActionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a clean node failure
            raise ActionError(str(exc)) from exc
        return {"recordId": getattr(record, "id", None)}

    changes: Dict[str, Dict[str, Any]] = {}
    for attr, new_value in pending.items():
        old_value = getattr(record, attr, None)
        if str(old_value) != new_value:
            setattr(record, attr, new_value)
            changes[attr] = {"from": old_value, "to": new_value}
    if changes:
        db.add(record)
        db.flush()
        # Its write is a domain event → may trigger other workflows (loop-guarded).
        emit_entity_event(
            db, entity.entity_type, "updated", record, tenant_id=tenant_id, actor_id=None, changes=changes
        )
    return {"recordId": getattr(record, "id", None)}
