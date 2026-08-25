"""Workflow-engine action executors for omnichannel (plan sprint-4/17).

Module code depending on its own repos/services - not core depending on a
module (the module registers these into the core workflow-engine registry via
its own boot hook, ``workflow_nodes.py::register_omnichannel_workflow_nodes``,
mirroring the module governance seam already used for capabilities).
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.repositories.module_repository import ModuleRepository
from app.workflow_engine.context import render_field

from ..models import Status
from ..repositories.contact_repository import ContactRepository
from ..schemas import SendMessageRequest
from .conversation_service import ThreadNotFound
from .message_service import MessageService, SendRejected


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


def _require_module_active(db: Session, tenant_id: str) -> None:
    if not ModuleRepository(db).is_active(tenant_id, "omnichannel"):
        raise ActionError("The omnichannel service is not active.")


def _contact_id(config: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    contact_id = render_field(config.get("contactId"), ctx).strip()
    if not contact_id:
        raise ActionError("Contact is empty after merging.")
    return contact_id


def omnichannel_get_contact(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact_id = _contact_id(config, ctx)
    contact = ContactRepository(db).get_by_id(contact_id, tenant_id)
    if contact is None:
        raise ActionError("Contact not found.")
    name = " ".join(part for part in [contact.first_name, contact.last_name] if part).strip()
    status = (
        db.query(Status.key)
        .filter(
            Status.id == contact.status_id,
            Status.tenant_id == tenant_id,
            Status.scope == "THREAD",
        )
        .scalar()
        or "OPEN"
    )
    return {
        "id": contact.id,
        "name": name or contact.phone or "",
        "phone": contact.phone or "",
        "email": contact.email or "",
        "workspaceId": contact.workspace_id,
        "statusId": contact.status_id,
        "status": status,
    }


def omnichannel_send_message(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact_id = _contact_id(config, ctx)
    text = render_field(config.get("message"), ctx)
    if not text.strip():
        raise ActionError("Message is empty after merging.")
    try:
        item = MessageService(db).send_message(
            contact_id,
            tenant_id,
            actor_user_id=None,
            payload=SendMessageRequest(messageType="TEXT", body=text),
        )
    except ThreadNotFound as exc:
        raise ActionError("Contact not found.") from exc
    except SendRejected as exc:
        raise ActionError(exc.message) from exc
    return {"messageId": item.id, "status": item.deliveryStatus or "QUEUED"}
