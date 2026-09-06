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
from .conversation_service import InvalidPatch, ThreadNotFound
from .message_service import MessageService, SendRejected

# plan 28 S3 (§5.5, AC-TEM-32) - the `mode` config value → the exact
# assignment shape passed to `ConversationService.patch_thread`.
ASSIGN_MODES = ("user", "team", "unassign")


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
            channel_id_override=str(ctx.get("trigger.channel.id") or "") or None,
            sandbox_only=ctx.get("_workflow.sandboxOnly") is True,
        )
    except ThreadNotFound as exc:
        raise ActionError("Contact not found.") from exc
    except SendRejected as exc:
        raise ActionError(exc.message) from exc
    return {"messageId": item.id, "status": item.deliveryStatus or "QUEUED"}


def omnichannel_assign_conversation(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """`omnichannel.assign_conversation` (plan 28 S3, §5.5, D-A8-5, AC-TEM-32).

    Routes through the ONE `ConversationService.patch_thread` write seam - the
    identical realtime push, consumer webhook and `conversation_events` row
    every other assignment path gets. `assigned_via_override="workflow"` +
    the run's ids (from `_workflow.workflowId`/`_workflow.runId`, set by the
    executor for every node - see `executor.py`) attribute the event to this
    run rather than to a human actor (D-A8 pinned decision: `actor=None`,
    never the workflow's publishing user).
    """
    _require_module_active(db, tenant_id)
    contact_id = _contact_id(config, ctx)
    mode = config.get("mode")
    if mode not in ASSIGN_MODES:
        raise ActionError("Assignment mode is not configured.")

    from .conversation_service import ConversationService

    kwargs: Dict[str, Any] = {
        "assigned_via_override": "workflow",
        "workflow_id": ctx.get("_workflow.workflowId"),
        "workflow_run_id": ctx.get("_workflow.runId"),
    }
    if mode == "user":
        user_id = render_field(config.get("userId"), ctx).strip()
        if not user_id:
            raise ActionError("User is empty after merging.")
        kwargs["assigned_user_id"] = user_id
    elif mode == "team":
        team_id = config.get("teamId")
        if not team_id:
            raise ActionError("Team is not configured.")
        kwargs["assigned_team_id"] = team_id
        # "default" (the picker's own sentinel, §5.5) means "use the team's
        # saved strategy" - `patch_thread`/`team_assignment_service.pick`
        # already treat `strategy_override=None` that way, so only a REAL
        # override value is forwarded.
        strategy = config.get("strategy")
        if strategy and strategy != "default":
            kwargs["strategy_override"] = strategy
    else:  # "unassign" - clears both sides unconditionally (§5.2 table).
        kwargs["assigned_user_id"] = None
        kwargs["assigned_team_id"] = None

    try:
        item = ConversationService(db).patch_thread(contact_id, tenant_id, **kwargs)
    except ThreadNotFound as exc:
        raise ActionError("Contact not found.") from exc
    except InvalidPatch as exc:
        # `exc.message` never embeds the raw id (D-A8-5 pinned wording -
        # "Team not found or inactive." / "Assignee not found in this
        # tenant." / "User is not a member of this team.").
        raise ActionError(exc.message) from exc

    return {
        "assignedUserId": item.assignedUserId,
        "assignedTeamId": item.assignedTeamId,
        # AC-TEM-35: `assigned` tracks whether a USER ended up owning the
        # thread - a team assignment with an empty roster is still a SUCCESS
        # (D-A8-11), just with `assigned = false` (the team is set, no user
        # is), never an ActionError.
        "assigned": bool(item.assignedUserId),
    }
