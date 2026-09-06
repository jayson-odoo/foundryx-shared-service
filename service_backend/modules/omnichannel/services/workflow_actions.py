"""Workflow-engine action executors for omnichannel (plan sprint-4/17,
extended plan sprint-4/31 S2 with the "simple steps" - assign, tags, field,
lifecycle, open/close, comment, template send; S4 with the two PARKING steps -
ask a question, wait).

Module code depending on its own repos/services - not core depending on a
module (the module registers these into the core workflow-engine registry via
its own boot hook, ``workflow_nodes.py::register_omnichannel_workflow_nodes``,
mirroring the module governance seam already used for capabilities).

D-A5-5: every step routes through the SAME write seam the UI uses
(``patch_thread`` / ``close_thread`` / ``lifecycle_service.move`` /
``ContactProfileService.patch`` / ``MessageService.send_message`` /
``add_internal_note``) so a workflow write emits the identical conversation
event, realtime push and consumer webhook. Each step COMMITS its own write
immediately (matching the UI's synchronous commit) rather than deferring to
the run's end-of-loop commit - AC-WFP-32 documents that an already-committed
step is never rolled back by a later node's failure.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories.module_repository import ModuleRepository
from app.workflow_engine.context import render_field

from ..models import Contact, Status, Workspace, WorkspaceMember
from app.models.status import Status as CoreStatus
from app.models.user import User
from ..repositories.contact_repository import ContactRepository
from ..schemas import SendMessageRequest
from .close_reason_service import CloseReasonInactive, CloseReasonNotFound
from .contact_field_service import ContactFieldService
from .contact_profile_service import ContactProfileService, ProfilePatchError
from .contact_tag_service import ContactTagService, TagValidationError
from .conversation_service import (
    ConversationService,
    InvalidPatch,
    ThreadAlreadyClosed,
    ThreadNotFound,
)
from .lifecycle_service import LifecycleStageNotFound
from .lifecycle_service import move as lifecycle_move
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


def _load_contact(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Contact:
    """AC-WFP-34: every contact id an A5 step resolves is looked up tenant-
    scoped - never a bare id lookup. A foreign/unknown contact fails the node
    with an id-free message."""
    contact_id = _contact_id(config, ctx)
    contact = ContactRepository(db).get_by_id(contact_id, tenant_id)
    if contact is None:
        raise ActionError("Contact not found.")
    return contact


def _fan_out_contact(db: Session, contact: Contact, tenant_id: str) -> None:
    """The ONE realtime + consumer-webhook fan-out every `contact.updated`
    producer uses (mirrors `ContactAdminService`'s bulk mutations, which call
    this same "private" method cross-service - an established precedent)."""
    conv = ConversationService(db)
    item = conv.thread_item(contact)
    conv._publish_contact_updated(contact, item, tenant_id)


def omnichannel_get_contact(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
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


def _rendered_kv_values(rows: Any, ctx: Dict[str, Any]) -> List[str]:
    """`templateVariables`'s `WorkflowKeyValue[]` rows, in the given (author-
    ordered) order, each value merge-rendered - the row `key` is a human label
    only (Meta's `{{n}}` placeholders are positional, not named)."""
    if not isinstance(rows, list):
        return []
    out: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(render_field(row.get("value"), ctx))
    return out


def _send_configured_message(
    db: Session,
    tenant_id: str,
    config: Dict[str, Any],
    ctx: Dict[str, Any],
    *,
    contact_id: str,
    text_override: Optional[str] = None,
) -> Any:
    """The ONE send path both `omnichannel.send_message` and
    `omnichannel.ask_question` use (`mode: text | template`) - template mode
    reuses `MessageService.send_message`'s own approval + placeholder-count
    validation, text mode merge-renders `config.message` unless the caller
    supplies `text_override` (the Ask node appends its numbered choices)."""
    mode = str(config.get("mode") or "text")
    sandbox_only = ctx.get("_workflow.sandboxOnly") is True
    channel_override = str(ctx.get("trigger.channel.id") or "") or None
    try:
        if mode == "template":
            template_id = str(config.get("templateId") or "").strip()
            if not template_id:
                raise ActionError("Template is not configured.")
            variables = _rendered_kv_values(config.get("templateVariables"), ctx)
            item = MessageService(db).send_message(
                contact_id,
                tenant_id,
                actor_user_id=None,
                payload=SendMessageRequest(
                    messageType="TEMPLATE", templateId=template_id, templateVariables=variables
                ),
                channel_id_override=channel_override,
                sandbox_only=sandbox_only,
            )
        else:
            text = (
                text_override
                if text_override is not None
                else render_field(config.get("message"), ctx)
            )
            if not text.strip():
                raise ActionError("Message is empty after merging.")
            item = MessageService(db).send_message(
                contact_id,
                tenant_id,
                actor_user_id=None,
                payload=SendMessageRequest(messageType="TEXT", body=text),
                channel_id_override=channel_override,
                sandbox_only=sandbox_only,
            )
    except ThreadNotFound as exc:
        raise ActionError("Contact not found.") from exc
    except SendRejected as exc:
        raise ActionError(exc.message) from exc
    return item


def omnichannel_send_message(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """AC-WFP-31/32: `mode: text | template` over the ONE `MessageService.
    send_message` path - template mode reuses its own approval + placeholder-
    count validation, text mode is unchanged from plan 17."""
    _require_module_active(db, tenant_id)
    contact_id = _contact_id(config, ctx)
    item = _send_configured_message(db, tenant_id, config, ctx, contact_id=contact_id)
    return {"messageId": item.id, "status": item.deliveryStatus or "QUEUED"}


# ── omnichannel.assign_conversation (AC-WFP-23/24) ──────────────────────────


def _round_robin_pick(db: Session, tenant_id: str, workspace: Workspace) -> Optional[str]:
    """AC-WFP-24: eligible members are workspace members that still resolve to
    a LIVE user in the SAME tenant, ordered stably (insertion order); the next
    pick follows the workspace's stored cursor. Returns None (no eligible
    member) rather than raising - an empty roster never fails the node.

    Plan 31 S3 review nit: does NOT mutate `workspace.round_robin_cursor` -
    the caller advances it only after the assign actually SUCCEEDS
    (`_advance_round_robin_cursor` below). Advancing it here meant a
    subsequent `InvalidPatch` still persisted the advance at the run's
    terminal commit, silently skipping a member who was never assigned."""
    rows = (
        db.query(WorkspaceMember.user_id)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(
            WorkspaceMember.tenant_id == tenant_id,
            WorkspaceMember.workspace_id == workspace.id,
            User.tenant_id == tenant_id,
            User.is_trashed.is_(False),
        )
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .all()
    )
    eligible = [r[0] for r in rows]
    if not eligible:
        return None
    cursor = workspace.round_robin_cursor
    idx = (eligible.index(cursor) + 1) % len(eligible) if cursor in eligible else 0
    return eligible[idx]


def _advance_round_robin_cursor(db: Session, workspace: Workspace, chosen: str) -> None:
    workspace.round_robin_cursor = chosen
    db.add(workspace)


def omnichannel_assign_conversation(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """AC-WFP-23: assign to a specific user, round-robin across the contact's
    OWN workspace members, or unassign - every path through `patch_thread` so
    the conversation event/realtime/webhook match the UI exactly.

    NOTE for the A8 merge (plan 28, `omnichannel.assign_conversation`): this
    key/field set (`contactId`/`workspaceId`/`mode`/`userId`, modes `user` |
    `round_robin` | `unassign`) is defined here because A8 has not merged onto
    this base - if A8 lands first, EXTEND its action with the `round_robin`
    mode instead of a second action (`team` mode stays A8's). The `workspaceId`
    config field is author-facing only (FE always shows it, unlike the plan's
    `show_when`) - runtime picks the contact's OWN `workspace_id` as the
    authoritative round-robin scope, never the picker's stale copy."""
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    mode = str(config.get("mode") or "user")

    if mode == "unassign":
        try:
            ConversationService(db).patch_thread(
                contact.id, tenant_id, assigned_user_id=None, actor=None,
                assigned_via_override="workflow",
            )
        except InvalidPatch as exc:
            raise ActionError(str(exc)) from exc
        return {"assignedUserId": None, "assigned": False}

    if mode == "round_robin":
        workspace = (
            db.query(Workspace)
            .filter(Workspace.id == contact.workspace_id, Workspace.tenant_id == tenant_id)
            .first()
        )
        chosen = _round_robin_pick(db, tenant_id, workspace) if workspace is not None else None
        if chosen is None:
            # AC-WFP-24: an empty roster never fails an automation.
            return {"assignedUserId": None, "assigned": False}
        try:
            ConversationService(db).patch_thread(
                contact.id, tenant_id, assigned_user_id=chosen, actor=None,
                assigned_via_override="workflow",
            )
        except InvalidPatch as exc:
            raise ActionError(str(exc)) from exc
        # Cursor advances ONLY on a successful assign (plan 31 S3 review nit).
        _advance_round_robin_cursor(db, workspace, chosen)
        return {"assignedUserId": chosen, "assigned": True}

    # mode == "user"
    user_id = str(config.get("userId") or "").strip()
    if not user_id:
        raise ActionError("User is not configured.")
    try:
        ConversationService(db).patch_thread(
            contact.id, tenant_id, assigned_user_id=user_id, actor=None,
            assigned_via_override="workflow",
        )
    except InvalidPatch as exc:
        raise ActionError(str(exc)) from exc
    return {"assignedUserId": user_id, "assigned": True}


# ── omnichannel.add_tag / omnichannel.remove_tag (AC-WFP-25) ────────────────


def _tag_action(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any], *, add: bool
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    tag_id = str(config.get("tagId") or "").strip()
    if not tag_id:
        raise ActionError("Tag is not configured.")
    tags_svc = ContactTagService(db)
    try:
        tags_svc.validate_tag_ids(contact.workspace_id, tenant_id, [tag_id])
    except TagValidationError as exc:
        raise ActionError(exc.message) from exc
    current = set(tags_svc.ids_for_contact(contact.id, tenant_id))
    new_ids = (current | {tag_id}) if add else (current - {tag_id})
    changed = new_ids != current
    if changed:
        try:
            ContactProfileService(db).patch(
                contact, tag_ids=sorted(new_ids), actor=None, actor_id=None
            )
        except ProfilePatchError as exc:
            raise ActionError("; ".join(exc.errors.values())) from exc
        db.commit()
        db.refresh(contact)
        _fan_out_contact(db, contact, tenant_id)
    return {"tags": sorted(new_ids), "changed": changed}


def omnichannel_add_tag(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    return _tag_action(db, tenant_id, config, ctx, add=True)


def omnichannel_remove_tag(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    return _tag_action(db, tenant_id, config, ctx, add=False)


# ── omnichannel.update_field (AC-WFP-26) ────────────────────────────────────


def _coerce_field_value(field_type: str, raw: str) -> Any:
    """Best-effort string → typed coercion for a merge-rendered value (the
    action only has plain text to work with, unlike the JSON-typed internal
    PATCH). An unparsable value is passed through unchanged so `validate_
    values`' own type check produces the standard field-error message."""
    if field_type == "number":
        try:
            f = float(raw)
        except ValueError:
            return raw
        return int(f) if f.is_integer() else f
    if field_type == "checkbox":
        low = raw.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no", ""):
            return False
        return raw
    return raw


def omnichannel_update_field(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    field_key = str(config.get("fieldKey") or "").strip()
    if not field_key:
        raise ActionError("Field is not configured.")
    fields_svc = ContactFieldService(db)
    field = next(
        (f for f in fields_svc.list(contact.workspace_id, tenant_id) if f.key == field_key), None
    )
    if field is None:
        raise ActionError(f'Field "{field_key}" not found in this workspace.')

    clear = config.get("clear") is True
    if clear:
        value: Any = None
    else:
        rendered = render_field(config.get("value"), ctx)
        value = _coerce_field_value(field.type, rendered)

    clean, errors = fields_svc.validate_values(contact.workspace_id, tenant_id, {field_key: value})
    if errors:
        raise ActionError("; ".join(errors.values()))

    try:
        changes = ContactProfileService(db).patch(
            contact, custom_fields=clean, actor=None, actor_id=None
        )
    except ProfilePatchError as exc:
        raise ActionError("; ".join(exc.errors.values())) from exc
    if changes:
        db.commit()
        db.refresh(contact)
        _fan_out_contact(db, contact, tenant_id)
    return {"fieldKey": field_key, "value": clean.get(field_key)}


# ── omnichannel.update_lifecycle (AC-WFP-27) ────────────────────────────────


def omnichannel_update_lifecycle(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    to_stage_id = str(config.get("toStageId") or "").strip()
    if not to_stage_id:
        raise ActionError("Target stage is not configured.")
    from app.services.status_machine import (
        TransitionConditionsNotMet,
        TransitionForbidden,
        TransitionNotAllowed,
    )

    from_stage_id = contact.lifecycle_status_id
    try:
        lifecycle_move(db, contact, to_stage_id, actor=None)
    except LifecycleStageNotFound as exc:
        raise ActionError("Stage not found in this contact's workspace.") from exc
    except (TransitionNotAllowed, TransitionForbidden, TransitionConditionsNotMet) as exc:
        raise ActionError(str(exc)) from exc
    db.commit()
    db.refresh(contact)
    stage_label = (
        db.query(CoreStatus.label)
        .filter(CoreStatus.id == to_stage_id, CoreStatus.tenant_id == tenant_id)
        .scalar()
    )
    _fan_out_contact(db, contact, tenant_id)
    return {"fromStageId": from_stage_id, "toStageId": to_stage_id, "stageLabel": stage_label}


# ── omnichannel.open_conversation / close_conversation (AC-WFP-28/29) ──────


def omnichannel_open_conversation(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    conv = ConversationService(db)
    current_key = conv.status_keys(tenant_id).get(contact.status_id)
    if current_key == "OPEN":
        return {"status": "OPEN", "changed": False}
    item = conv.patch_thread(contact.id, tenant_id, status="OPEN", actor=None)
    return {"status": item.status, "changed": True}


def omnichannel_close_conversation(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    close_reason_id = str(config.get("closeReasonId") or "").strip()
    if not close_reason_id:
        raise ActionError("Close reason is not configured.")
    note = render_field(config.get("note"), ctx).strip() or None
    try:
        item = ConversationService(db).close_thread(
            contact.id, tenant_id, close_reason_id=close_reason_id, note=note, actor=None,
        )
    except ThreadAlreadyClosed as exc:
        raise ActionError("This conversation is already closed.") from exc
    except CloseReasonNotFound as exc:
        raise ActionError("Close reason not found in this workspace.") from exc
    except CloseReasonInactive as exc:
        raise ActionError("Close reason is inactive.") from exc
    return {"status": item.status, "closeReasonId": close_reason_id}


# ── omnichannel.add_comment (AC-WFP-30) ─────────────────────────────────────


def omnichannel_add_comment(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    _require_module_active(db, tenant_id)
    contact = _load_contact(db, tenant_id, config, ctx)
    body = render_field(config.get("body"), ctx)
    if not body.strip():
        raise ActionError("Comment is empty after merging.")
    try:
        item = MessageService(db).add_internal_note(contact.id, tenant_id, actor_user_id=None, body=body)
    except ThreadNotFound as exc:
        raise ActionError("Contact not found.") from exc
    except SendRejected as exc:
        raise ActionError(exc.message) from exc
    return {"messageId": item.id}


# ── omnichannel.ask_question / omnichannel.wait (AC-WFP-43/44/50/53) ────────


def _parked_run_ids(ctx: Dict[str, Any]) -> tuple:
    """The parking preconditions every suspending node shares: a real persisted
    run to park, and a walk that can actually be resumed (never a debug pass)."""
    run_id = str(ctx.get("_workflow.runId") or "")
    workflow_id = str(ctx.get("_workflow.workflowId") or "")
    node_id = str(ctx.get("_workflow.nodeId") or "")
    if not (run_id and workflow_id and node_id):
        raise ActionError("This step can only run inside a workflow run.")
    if ctx.get("_workflow.canPark") is not True:
        raise ActionError("This step cannot be executed on its own - run the whole workflow.")
    return run_id, workflow_id, node_id


def omnichannel_ask_question(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """AC-WFP-43/44/51/53: send the configured question through the ONE send
    path, write ONE wait row keyed (tenant, workspace, contact) with the answer
    spec + deadline, then PARK the run (`WorkflowPaused`). It never returns an
    output - the resume supplies `answer`/`answerRaw`/`answerKey`/`timedOut`/
    `reason` when the contact replies or the deadline passes."""
    from app.workflow_engine.parking import WorkflowPaused

    from . import workflow_waits as waits

    _require_module_active(db, tenant_id)
    run_id, workflow_id, node_id = _parked_run_ids(ctx)
    contact = _load_contact(db, tenant_id, config, ctx)

    answer_type = str(config.get("answerType") or "text").strip().lower()
    if answer_type not in waits.ANSWER_TYPES:
        raise ActionError("Answer type is not configured.")
    choices = [str(c).strip() for c in (config.get("choices") or []) if str(c).strip()]
    if answer_type == "choice":
        if not choices:
            raise ActionError("Choices are not configured.")
        if len(choices) > waits.MAX_CHOICES:
            raise ActionError(f"A question can offer at most {waits.MAX_CHOICES} choices.")
    try:
        retry_limit = int(str(config.get("retryLimit") or 0))
    except ValueError as exc:
        raise ActionError("Retry limit must be a number.") from exc
    if retry_limit < 0 or retry_limit > waits.MAX_RETRY_LIMIT:
        raise ActionError(f"Retry limit must be between 0 and {waits.MAX_RETRY_LIMIT}.")

    # Deadline BEFORE the send: a misconfigured timeout must not leave the
    # contact holding a question nobody will ever resume.
    deadline = datetime.now(timezone.utc) + waits.duration_to_delta(
        config.get("timeoutValue"), config.get("timeoutUnit")
    )
    # One open question per contact (D-A5-9) - checked BEFORE sending, so a
    # refused second Ask never messages the contact.
    if waits.find_open_question(db, tenant_id, contact.id) is not None:
        raise ActionError("This contact already has an open question.")

    spec: Dict[str, Any] = {
        "answerType": answer_type,
        "choices": choices,
        "retryLimit": retry_limit,
        "retryMessage": render_field(config.get("retryMessage"), ctx),
        "question": render_field(config.get("message"), ctx),
        # The resume path has no run context - pin what a re-ask needs now.
        "channelId": str(ctx.get("trigger.channel.id") or "") or None,
        "sandboxOnly": ctx.get("_workflow.sandboxOnly") is True,
    }
    sent_text = waits.question_text(spec)
    # Template mode sends the approved template as authored (Meta owns the
    # body) - the numbered choice list is a TEXT-mode affordance only; either
    # way the answer matcher accepts the label or its number.
    item = _send_configured_message(
        db, tenant_id, config, ctx, contact_id=contact.id,
        text_override=sent_text if str(config.get("mode") or "text") != "template" else None,
    )

    try:
        waits.open_wait(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            workflow_id=workflow_id,
            node_id=node_id,
            kind=waits.KIND_QUESTION,
            deadline_at=deadline,
            contact=contact,
            answer_spec=spec,
            is_test=ctx.get("_workflow.isTest") is True,
        )
    except waits.WaitError as exc:
        raise ActionError(str(exc)) from exc
    db.commit()

    raise WorkflowPaused(
        output={
            "waiting": True,
            "kind": waits.KIND_QUESTION,
            "question": sent_text,
            "answerType": answer_type,
            "choices": choices,
            "retryLimit": retry_limit,
            "messageId": item.id,
            "timeoutAt": deadline.isoformat().replace("+00:00", "Z"),
        }
    )


def omnichannel_wait(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """AC-WFP-50: park the run on a bare deadline. The wait row carries NO
    contact, so an inbound message never shortens it - only the beat sweep
    resumes it, on the node's single out port."""
    from app.workflow_engine.parking import WorkflowPaused

    from . import workflow_waits as waits

    _require_module_active(db, tenant_id)
    run_id, workflow_id, node_id = _parked_run_ids(ctx)
    try:
        delta = waits.duration_to_delta(config.get("waitValue"), config.get("waitUnit"))
    except waits.WaitError as exc:
        raise ActionError(str(exc)) from exc
    deadline = datetime.now(timezone.utc) + delta
    try:
        waits.open_wait(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            workflow_id=workflow_id,
            node_id=node_id,
            kind=waits.KIND_DELAY,
            deadline_at=deadline,
            is_test=ctx.get("_workflow.isTest") is True,
        )
    except waits.WaitError as exc:
        raise ActionError(str(exc)) from exc
    db.commit()
    raise WorkflowPaused(
        output={
            "waiting": True,
            "kind": waits.KIND_DELAY,
            "resumeAt": deadline.isoformat().replace("+00:00", "Z"),
        }
    )


# ── omnichannel.business_hours (plan sprint-4/31 S5, AC-WFP-56) ─────────────


def omnichannel_business_hours(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """Branch by whether "now" falls inside the workspace's configured
    business hours (workspace row -> tenant default -> fails loudly rather
    than guessing, AC-WFP-56). A registry-driven BRANCHING action (D-A5-14) -
    the executor's generic `ports`/`branch` seam, no special case here."""
    from .business_hours import MissingBusinessHours, evaluate

    _require_module_active(db, tenant_id)
    workspace_id = render_field(config.get("workspaceId"), ctx).strip()
    if not workspace_id:
        raise ActionError("Workspace is empty after merging.")
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.is_trashed.is_(False),
        )
        .first()
    )
    if workspace is None:
        raise ActionError("Workspace not found.")
    try:
        is_open, tzname, checked_at = evaluate(db, tenant_id, workspace_id)
    except MissingBusinessHours as exc:
        raise ActionError(str(exc)) from exc
    return {
        "isOpen": is_open,
        "checkedAt": checked_at.isoformat().replace("+00:00", "Z"),
        "timezone": tzname,
        "branch": "inside" if is_open else "outside",
    }
