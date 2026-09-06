"""Omnichannel workflow-engine node registration (plan sprint-4/17, extended
plan sprint-4/31 S1 with the conversation/contact triggers + once-per-contact).

Called from ``bootstrap.py::register_engine_entities()`` - the existing,
already-wired module boot hook (``app/module_loader.py::register_module_boot``)
- so this module never needs a core file to import it directly (module
governance: hook via the predefined seam, no global-store injection).
"""
from typing import Any, Dict

from app.workflow_engine.registry import ActionDef, NodeField, NodeOutput, TriggerDef, register_action, register_trigger

from .services.workflow_actions import (
    omnichannel_add_comment,
    omnichannel_add_tag,
    omnichannel_assign_conversation,
    omnichannel_close_conversation,
    omnichannel_get_contact,
    omnichannel_open_conversation,
    omnichannel_remove_tag,
    omnichannel_send_message,
    omnichannel_update_field,
    omnichannel_update_lifecycle,
)
from .services.workflow_test_data import build_test_payload, test_metadata

MODULE_NAME = "omnichannel"

# The `triggerOncePerContact` checkbox every plan-31 contact trigger offers
# (D-A5-4) - a shared field object (mirror of the frontend's
# TRIGGER_ONCE_PER_CONTACT_FIELD constant in lib/workflow-catalog.ts).
_TRIGGER_ONCE_PER_CONTACT_FIELD = NodeField(
    key="triggerOncePerContact", label="Trigger once per contact", type="boolean"
)


# ── shared refine/context_extra helpers (plan sprint-4/31) ──────────────────


def _workspace_ok(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    wanted = config.get("workspaceId")
    if not wanted:
        return True
    facts = ev.get("record_facts") or {}
    return wanted == facts.get("record.workspaceId")


def _contact_base_context(ev: Dict[str, Any]) -> Dict[str, Any]:
    """`trigger.contact.*`/`trigger.conversationId`/`trigger.workspaceId` -
    shared by every contact-scoped trigger's `context_extra` (dotted keys;
    the executor's generic `eventData` flatten prefixes them `trigger.`)."""
    facts = ev.get("record_facts") or {}
    name = " ".join(
        part for part in [facts.get("record.firstName"), facts.get("record.lastName")] if part
    ).strip()
    return {
        "contact.id": ev.get("record_id"),
        "contact.name": name or facts.get("record.phone") or "",
        "contact.phone": facts.get("record.phone"),
        "conversationId": ev.get("record_id"),
        "workspaceId": facts.get("record.workspaceId"),
    }


def _once_per_contact_fire_guard(db, wf, config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    """AC-WFP-15: consulted generically by `entity_events._match_and_enqueue`
    for every TriggerDef that sets this as its `fire_guard`. No-op (always
    fires) unless the author checked "Trigger once per contact"."""
    if not config.get("triggerOncePerContact"):
        return True
    contact_id = ev.get("record_id")
    if not contact_id:
        return True
    from .services.workflow_fire_store import claim_fire

    return claim_fire(db, tenant_id=wf.tenant_id, workflow_id=wf.id, contact_id=contact_id)


def _once_per_contact_fire_guard_from_extra(db, wf, config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    """Same as `_once_per_contact_fire_guard`, for a trigger whose event
    ``record_id`` is NOT the contact (e.g. `message_received`'s record is the
    message) - the contact id lives in ``extra.contactId`` instead."""
    if not config.get("triggerOncePerContact"):
        return True
    contact_id = (ev.get("extra") or {}).get("contactId")
    if not contact_id:
        return True
    from .services.workflow_fire_store import claim_fire

    return claim_fire(db, tenant_id=wf.tenant_id, workflow_id=wf.id, contact_id=contact_id)


def _delete_fires_on_workflow_deleted(db, ev: Dict[str, Any]) -> None:
    """AC-WFP-15: "once-per-contact" markers are deleted WITH the workflow.
    Registered as a generic core event subscriber (`register_event_subscriber`,
    plan sprint-2/10 D5) - reuses the seam core already fires
    `workflow`/`deleted` through (`WorkflowService.remove`), no core edit."""
    if ev.get("entity_type") != "workflow" or ev.get("action") != "deleted":
        return
    workflow_id = ev.get("record_id")
    tenant_id = ev.get("tenant_id")
    if not workflow_id or not tenant_id:
        return
    from .services.workflow_fire_store import delete_for_workflow

    delete_for_workflow(db, tenant_id, workflow_id)


# ── conversation_opened ──────────────────────────────────────────────────────


def _opened_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    if not _workspace_ok(config, ev):
        return False
    extra = ev.get("extra") or {}
    if config.get("channelId") and config["channelId"] != extra.get("channelId"):
        return False
    if config.get("reopenOnly") and not extra.get("isReopen"):
        return False
    return True


def _opened_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    extra = ev.get("extra") or {}
    return {
        **_contact_base_context(ev),
        "isReopen": extra.get("isReopen"),
        "channelId": extra.get("channelId"),
    }


# ── conversation_closed ──────────────────────────────────────────────────────


def _closed_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    if not _workspace_ok(config, ev):
        return False
    wanted_reason = config.get("closeReasonId")
    if not wanted_reason:
        return True
    return wanted_reason == (ev.get("extra") or {}).get("closeReasonId")


def _closed_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    extra = ev.get("extra") or {}
    return {
        **_contact_base_context(ev),
        "closeReasonId": extra.get("closeReasonId"),
        "closeReasonLabel": extra.get("closeReasonLabel"),
        "note": extra.get("note"),
    }


# ── conversation_assigned ────────────────────────────────────────────────────


def _assigned_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    if not _workspace_ok(config, ev):
        return False
    extra = ev.get("extra") or {}
    if config.get("onUnassign"):
        return extra.get("assigneeUserId") is None
    wanted = config.get("assigneeUserId")
    if not wanted:
        return True
    return wanted == extra.get("assigneeUserId")


def _assigned_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    extra = ev.get("extra") or {}
    return {
        **_contact_base_context(ev),
        "assigneeUserId": extra.get("assigneeUserId"),
        "previousAssigneeUserId": extra.get("previousAssigneeUserId"),
        "assignedVia": extra.get("assignedVia"),
    }


# ── contact_tag_added / contact_tag_removed ─────────────────────────────────


def _tag_delta(added: bool, changes: Dict[str, Any]):
    tag_change = changes.get("tags") or {}
    before = set(tag_change.get("from") or [])
    after = set(tag_change.get("to") or [])
    return (after - before) if added else (before - after)


def _make_tag_refine(added: bool):
    def refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
        if not _workspace_ok(config, ev):
            return False
        changes = ev.get("changes") or {}
        if "tags" not in changes:
            return False
        delta = _tag_delta(added, changes)
        if not delta:
            return False
        wanted = config.get("tagId")
        return not wanted or wanted in delta

    return refine


def _make_tag_context(added: bool):
    def context_extra(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
        changes = ev.get("changes") or {}
        delta = _tag_delta(added, changes)
        wanted = config.get("tagId")
        tag_id = wanted if wanted in delta else (sorted(delta)[0] if delta else None)
        names = (ev.get("extra") or {}).get("tagNames") or {}
        return {**_contact_base_context(ev), "tagId": tag_id, "tagName": names.get(tag_id)}

    return context_extra


# ── contact_field_changed ────────────────────────────────────────────────────


def _field_changed_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    if not _workspace_ok(config, ev):
        return False
    wanted_key = config.get("fieldKey")
    if not wanted_key:
        return False
    changes = ev.get("changes") or {}
    change = changes.get(f"customFields.{wanted_key}")
    if change is None:
        return False
    new_value = config.get("newValue")
    if new_value not in (None, ""):
        return str(change.get("to")) == str(new_value)
    return True


def _field_changed_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    key = config.get("fieldKey")
    changes = ev.get("changes") or {}
    change = changes.get(f"customFields.{key}") or {}
    return {
        **_contact_base_context(ev),
        "fieldKey": key,
        "fromValue": change.get("from"),
        "toValue": change.get("to"),
    }


# ── lifecycle_changed (rides the machine's OWN entity.status_changed) ───────


def _lifecycle_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    if not _workspace_ok(config, ev):
        return False
    extra = ev.get("extra") or {}
    from_ok = not config.get("fromStageId") or config.get("fromStageId") == extra.get("from_status_id")
    to_ok = not config.get("toStageId") or config.get("toStageId") == extra.get("to_status_id")
    return from_ok and to_ok


def _lifecycle_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    return {**_contact_base_context(ev)}


# ── broadcast_completed (A4, AC-WFP-22 - registered generically now) ────────


def _broadcast_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    wanted = config.get("workspaceId")
    if not wanted:
        return True
    return wanted == (ev.get("extra") or {}).get("workspaceId")


def _broadcast_context(config: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    extra = ev.get("extra") or {}
    return {
        "broadcastId": extra.get("broadcastId"),
        "broadcastName": extra.get("broadcastName"),
        "sent": extra.get("sent"),
        "failed": extra.get("failed"),
    }


# ── message_received (plan 17, extended plan 31 AC-WFP-14/15) ───────────────


def _message_received_refine(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    extra = ev.get("extra") or {}
    wanted_channel = config.get("channelId")
    if wanted_channel and wanted_channel != extra.get("channelId"):
        return False
    if config.get("firstMessageOnly") and not extra.get("isFirstMessage"):
        return False
    keyword = str(config.get("keywordContains") or "").strip()
    if keyword:
        text = str(extra.get("messageText") or "")
        if keyword.lower() not in text.lower():
            return False
    return True

def _contact_apply_update(db, record, changes, actor) -> None:
    """B11 (plan-25 round-3 codex triage): `entity.update`'s write path for
    `omnichannel_contact` - routes through `ConversationService.patch_thread`
    (the SAME seam the internal thread PATCH and the public gateway PATCH
    both use) instead of a raw `setattr` loop, so a workflow write gets the
    identical validation/normalization (`language`/`countryCode` format,
    `customFields`/`tagIds` - though only the scalar profile fields + priority
    are in this entity's `writable` whitelist today) AND the realtime +
    webhook `contact.updated` fan-out every other writer gets. `priority`
    (also writable) is a THREAD field `patch_thread` already accepts directly
    alongside the profile fields, so one call covers the whole whitelist.
    Raises a plain exception on invalid input - `entity_actions.entity_update`
    wraps it into the node's `ActionError` (this module deliberately does not
    import the core action-error type - a plain exception is enough)."""
    from .services.conversation_service import ConversationService, InvalidPatch
    from .services.contact_profile_service import ProfilePatchError

    try:
        ConversationService(db).patch_thread(record.id, record.tenant_id, actor=actor, **changes)
    except ProfilePatchError as exc:
        raise ValueError("; ".join(f"{f}: {m}" for f, m in exc.errors.items())) from exc
    except InvalidPatch as exc:
        raise ValueError(str(exc)) from exc


def _register_contact_entity() -> None:
    """Workflow-engine entity registration (plan 25 S1, AC-CDM-22) - registers
    ``record:omnichannel_contact`` facts (for IF conditions + entity triggers)
    and the ``entity.update`` writable whitelist.

    ``has_status=False`` DELIBERATELY (review round 1, finding 7 - the
    `WorkflowEntity.entity_type` used by `workflow_service.metadata()`'s
    status lookup and `entity_actions.entity_transition_status`'s
    `status_machine.transition()` call is `"omnichannel_contact"`, but the
    contact's ACTUAL machine is a WORKSPACE-SCOPED status entity registered
    as `"omnichannel_contact_lifecycle"` (`lifecycle_service.ENTITY_TYPE`,
    `scope_id=workspace_id` - no single tenant-wide status list exists to
    resolve). Leaving `has_status=True` produced an EMPTY status picker
    (foolproof-UI violation) and `entity.transition_status` raised
    `UnknownStatusEntity` at runtime for any author who tried it. `entity.
    status_changed` is UNAFFECTED by this flag - it is a fixed trigger in
    the catalog (not entity-gated) and the actual event emission already
    goes through the GENERIC `StatusEntity.workflow_entity_type` reverse
    pointer (`lifecycle_service.py`'s `omnichannel_contact_lifecycle`
    registration sets `workflow_entity_type="omnichannel_contact"`, so
    `status_machine.transition()` emits `entity.status_changed` keyed
    `omnichannel_contact` regardless of this flag - AC-CDM-24 stays green).
    `status_attr` is kept (harmless metadata, matches the model column) so a
    future fix (a per-entity `status_entity_type` resolving THROUGH the
    scoped-status registry) doesn't need to re-add it. Tracked as a backlog
    row (workflow status picker / transition action for scoped machines)."""
    from app.workflow_engine.entities import WorkflowEntity, register_workflow_entity

    from .models import Contact

    register_workflow_entity(
        WorkflowEntity(
            entity_type="omnichannel_contact",
            label="Contact",
            model=Contact,
            fact_attrs=(
                "first_name",
                "last_name",
                "phone",
                "email",
                "language",
                "country_code",
                "priority",
                "assigned_user_id",
                "csw_expires_at",
                "last_message_at",
                # plan sprint-4/31: every new contact-scoped trigger's `refine`/
                # `context_extra` needs the owning workspace (workspace-scoped
                # picker filters) - resolved generically off `trigger.record.
                # workspaceId` rather than a per-trigger DB lookup.
                "workspace_id",
            ),
            writable=frozenset(
                {"first_name", "last_name", "email", "language", "country_code", "priority"}
            ),
            has_status=False,
            status_attr="lifecycle_status_id",
            module=MODULE_NAME,
            apply_update=_contact_apply_update,
            # Plan sprint-4/27 (A3) - the conversation drawer's Shortcuts
            # control runs a published `entity.shortcut` workflow against the
            # open thread's contact record.
            supports_shortcut=True,
        )
    )


_TRIGGER_OUTPUTS = [
    NodeOutput("trigger.message.id", "Message · id"),
    NodeOutput("trigger.message.text", "Message · text"),
    NodeOutput("trigger.message.type", "Message · type"),
    NodeOutput("trigger.message.mediaUrl", "Message · media URL"),
    NodeOutput("trigger.contact.id", "Contact · id"),
    NodeOutput("trigger.contact.name", "Contact · name"),
    NodeOutput("trigger.contact.phone", "Contact · phone"),
    NodeOutput("trigger.channel.id", "Channel · id"),
    NodeOutput("trigger.channel.name", "Channel · name"),
    NodeOutput("trigger.conversationId", "Conversation id"),
]


# Output seed shared by every contact-scoped trigger below (plan sprint-4/31
# §5.2) - mirror of the frontend's OMNICHANNEL_CONTACT_TRIGGER_OUTPUTS.
_CONTACT_TRIGGER_OUTPUTS = [
    NodeOutput("trigger.contact.id", "Contact · id"),
    NodeOutput("trigger.contact.name", "Contact · name"),
    NodeOutput("trigger.contact.phone", "Contact · phone"),
    NodeOutput("trigger.conversationId", "Conversation id"),
    NodeOutput("trigger.workspaceId", "Workspace id"),
    NodeOutput("trigger.actor.name", "Actor name"),
    NodeOutput("trigger.actor.email", "Actor email"),
]


def register_omnichannel_workflow_nodes() -> None:
    """Idempotent (``register_trigger``/``register_action`` are dict-set)."""
    _register_contact_entity()
    register_trigger(
        TriggerDef(
            key="omnichannel.message_received",
            label="Incoming omnichannel message",
            description="Fires when a WhatsApp message arrives on a chosen channel (or any channel).",
            icon="MessageCircle",
            category="Triggers",
            module=MODULE_NAME,
            test_metadata_provider=test_metadata,
            test_payload_builder=build_test_payload,
            fields=[
                NodeField(
                    key="channelId",
                    label="Channel",
                    type="omnichannelChannel",
                    required=False,
                ),
                # plan sprint-4/31 (AC-WFP-14): extra filters, refined at match
                # time (never a second emission).
                NodeField(key="firstMessageOnly", label="First message only", type="boolean"),
                NodeField(key="keywordContains", label="Message contains", type="text"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=_TRIGGER_OUTPUTS,
            event_action="received",
            event_entity_type="omnichannel_message",
            refine=_message_received_refine,
            fire_guard=_once_per_contact_fire_guard_from_extra,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.conversation_opened",
            label="Conversation opened",
            description="Fires when a conversation moves to open (first contact or a reopen).",
            icon="FolderOpen",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="channelId", label="Channel", type="omnichannelChannel"),
                NodeField(key="reopenOnly", label="Only on reopen", type="boolean"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.isReopen", "Is reopen"),
                NodeOutput("trigger.channelId", "Channel id"),
            ],
            event_action="conversation_opened",
            event_entity_type="omnichannel_contact",
            refine=_opened_refine,
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_opened_context,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.conversation_closed",
            label="Conversation closed",
            description="Fires when a conversation is closed, optionally for one close reason.",
            icon="FolderX",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="closeReasonId", label="Close reason", type="omnichannelCloseReason"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.closeReasonId", "Close reason id"),
                NodeOutput("trigger.closeReasonLabel", "Close reason"),
                NodeOutput("trigger.note", "Note"),
            ],
            event_action="conversation_closed",
            event_entity_type="omnichannel_contact",
            refine=_closed_refine,
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_closed_context,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.conversation_assigned",
            label="Conversation assigned",
            description="Fires when a conversation is assigned, reassigned, or unassigned.",
            icon="UserCheck",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="assigneeUserId", label="Assignee", type="omnichannelMember"),
                NodeField(key="onUnassign", label="Only on unassign", type="boolean"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.assigneeUserId", "Assignee id"),
                NodeOutput("trigger.previousAssigneeUserId", "Previous assignee id"),
                NodeOutput("trigger.assignedVia", "Assigned via"),
            ],
            event_action="conversation_assigned",
            event_entity_type="omnichannel_contact",
            refine=_assigned_refine,
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_assigned_context,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.contact_tag_added",
            label="Contact tag added",
            description="Fires when a tag is added to a contact, optionally for one tag.",
            icon="Tag",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="tagId", label="Tag", type="omnichannelTag"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.tagId", "Tag id"),
                NodeOutput("trigger.tagName", "Tag name"),
            ],
            event_action="updated",
            event_entity_type="omnichannel_contact",
            refine=_make_tag_refine(added=True),
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_make_tag_context(added=True),
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.contact_tag_removed",
            label="Contact tag removed",
            description="Fires when a tag is removed from a contact, optionally for one tag.",
            icon="Tag",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="tagId", label="Tag", type="omnichannelTag"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.tagId", "Tag id"),
                NodeOutput("trigger.tagName", "Tag name"),
            ],
            event_action="updated",
            event_entity_type="omnichannel_contact",
            refine=_make_tag_refine(added=False),
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_make_tag_context(added=False),
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.contact_field_changed",
            label="Contact field updated",
            description="Fires when a registered custom field on a contact changes.",
            icon="PencilLine",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(
                    key="fieldKey", label="Field", type="omnichannelContactField", required=True
                ),
                NodeField(key="newValue", label="New value", type="text"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.fieldKey", "Field key"),
                NodeOutput("trigger.fromValue", "From value"),
                NodeOutput("trigger.toValue", "To value"),
            ],
            event_action="updated",
            event_entity_type="omnichannel_contact",
            refine=_field_changed_refine,
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_field_changed_context,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.lifecycle_changed",
            label="Lifecycle updated",
            description="Fires when a contact moves between lifecycle stages.",
            icon="Activity",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace"),
                NodeField(key="fromStageId", label="From stage", type="omnichannelLifecycleStage"),
                NodeField(key="toStageId", label="To stage", type="omnichannelLifecycleStage"),
                _TRIGGER_ONCE_PER_CONTACT_FIELD,
            ],
            outputs=[
                *_CONTACT_TRIGGER_OUTPUTS,
                NodeOutput("trigger.fromStatus", "From stage"),
                NodeOutput("trigger.toStatus", "To stage"),
                NodeOutput("trigger.toStageLabel", "To stage label"),
            ],
            # Rides the machine's EXISTING `entity.status_changed` emission on
            # `omnichannel_contact` (D-A5-3, F3) - NO second emission. A real
            # TriggerDef (not a frontend-only alias) because `omnichannel_
            # contact` is registered `has_status=False` (the lifecycle machine
            # is workspace-SCOPED - see `_register_contact_entity`'s comment
            # block) so a bare `entity.status_changed` node would render an
            # EMPTY status picker; this trigger carries its own workspace +
            # stage pickers instead.
            event_action="status_changed",
            event_entity_type="omnichannel_contact",
            refine=_lifecycle_refine,
            fire_guard=_once_per_contact_fire_guard,
            context_extra=_lifecycle_context,
        )
    )
    register_trigger(
        TriggerDef(
            key="omnichannel.broadcast_completed",
            label="Broadcast completed",
            description="Fires when a broadcast finishes sending.",
            icon="Megaphone",
            category="Triggers",
            module=MODULE_NAME,
            fields=[NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace")],
            outputs=[
                NodeOutput("trigger.broadcastId", "Broadcast id"),
                NodeOutput("trigger.broadcastName", "Broadcast name"),
                NodeOutput("trigger.sent", "Sent count"),
                NodeOutput("trigger.failed", "Failed count"),
            ],
            # Registered generically NOW (AC-WFP-07/22) even though plan 29
            # (A4) - the emitter - is not merged on this base: the registry
            # dispatch (`_trigger_types_for`/`_match_and_enqueue`) matches on
            # the `omnichannel_broadcast` `completed` domain event whenever it
            # exists, with NO further core or module edit once A4 lands.
            event_action="completed",
            event_entity_type="omnichannel_broadcast",
            refine=_broadcast_refine,
            context_extra=_broadcast_context,
        )
    )
    from app.workflow_engine.entity_events import register_event_subscriber

    register_event_subscriber(_delete_fires_on_workflow_deleted)

    register_action(
        ActionDef(
            key="omnichannel.get_contact",
            label="Get Contact",
            description="Load a contact by id into the workflow context.",
            icon="UserRound",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_get_contact,
            fields=[
                NodeField(
                    key="contactId",
                    label="Contact",
                    type="text",
                    required=True,
                    mergeable=True,
                )
            ],
            outputs=[
                NodeOutput("id", "Contact id"),
                NodeOutput("name", "Name"),
                NodeOutput("phone", "Phone"),
                NodeOutput("email", "Email"),
                NodeOutput("workspaceId", "Workspace id"),
                NodeOutput("statusId", "Status id"),
                NodeOutput("status", "Status"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.send_message",
            label="Send Message",
            description="Send a text or approved-template reply into a conversation.",
            icon="Send",
            category="Actions",
            module=MODULE_NAME,
            destructive=True,
            executor=omnichannel_send_message,
            fields=[
                NodeField(
                    key="contactId",
                    label="Contact",
                    type="text",
                    required=True,
                    mergeable=True,
                ),
                # plan sprint-4/31 S2 (AC-WFP-31): `mode: text | template` over
                # the ONE `MessageService.send_message` path - F7 (the service
                # already validated approval/placeholder-counts, this only
                # exposes it on the node).
                NodeField(
                    key="mode",
                    label="Message type",
                    type="select",
                    options=[
                        {"value": "text", "label": "Text message"},
                        {"value": "template", "label": "Approved template"},
                    ],
                ),
                NodeField(
                    key="message",
                    label="Message",
                    type="textarea",
                    required=True,
                    mergeable=True,
                    show_when=("mode", "text"),
                ),
                NodeField(
                    key="templateId",
                    label="Template",
                    type="whatsappTemplate",
                    required=True,
                    show_when=("mode", "template"),
                ),
                NodeField(
                    key="templateVariables",
                    label="Template variables",
                    type="templateParams",
                    show_when=("mode", "template"),
                ),
            ],
            outputs=[
                NodeOutput("messageId", "Message id"),
                NodeOutput("status", "Send status"),
            ],
        )
    )
    # ── plan sprint-4/31 S2 (A5a simple steps) ───────────────────────────────
    register_action(
        ActionDef(
            key="omnichannel.assign_conversation",
            label="Assign conversation",
            description="Assign, round-robin, or unassign a conversation.",
            icon="UserRoundCog",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_assign_conversation,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(
                    key="mode",
                    label="Assign mode",
                    type="select",
                    required=True,
                    options=[
                        {"value": "user", "label": "Specific user"},
                        {"value": "round_robin", "label": "Round robin"},
                        {"value": "unassign", "label": "Unassign"},
                    ],
                ),
                NodeField(
                    key="userId", label="User", type="omnichannelMember", required=True,
                    show_when=("mode", "user"),
                ),
            ],
            outputs=[
                NodeOutput("assignedUserId", "Assigned user id"),
                NodeOutput("assigned", "Assigned"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.add_tag",
            label="Add tag",
            description="Add a tag to a contact.",
            icon="Tag",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_add_tag,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(key="tagId", label="Tag", type="omnichannelTag", required=True),
            ],
            outputs=[NodeOutput("tags", "Tags"), NodeOutput("changed", "Changed")],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.remove_tag",
            label="Remove tag",
            description="Remove a tag from a contact.",
            icon="Tag",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_remove_tag,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(key="tagId", label="Tag", type="omnichannelTag", required=True),
            ],
            outputs=[NodeOutput("tags", "Tags"), NodeOutput("changed", "Changed")],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.update_field",
            label="Update contact field",
            description="Set or clear a registered custom field on a contact.",
            icon="PencilLine",
            category="Actions",
            module=MODULE_NAME,
            destructive=True,
            executor=omnichannel_update_field,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(key="fieldKey", label="Field", type="omnichannelContactField", required=True),
                NodeField(key="value", label="Value", type="text", mergeable=True),
                NodeField(key="clear", label="Clear the field", type="boolean"),
            ],
            outputs=[NodeOutput("fieldKey", "Field key"), NodeOutput("value", "Value")],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.update_lifecycle",
            label="Update lifecycle",
            description="Move a contact to a lifecycle stage through its state machine.",
            icon="Activity",
            category="Actions",
            module=MODULE_NAME,
            destructive=True,
            executor=omnichannel_update_lifecycle,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(
                    key="toStageId", label="Move to stage", type="omnichannelLifecycleStage", required=True
                ),
            ],
            outputs=[
                NodeOutput("fromStageId", "From stage id"),
                NodeOutput("toStageId", "To stage id"),
                NodeOutput("stageLabel", "Stage label"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.open_conversation",
            label="Open conversation",
            description="Reopen a closed or snoozed conversation.",
            icon="FolderOpen",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_open_conversation,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
            ],
            outputs=[NodeOutput("status", "Status"), NodeOutput("changed", "Changed")],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.close_conversation",
            label="Close conversation",
            description="Close a conversation with a reason and an optional note.",
            icon="FolderX",
            category="Actions",
            module=MODULE_NAME,
            destructive=True,
            executor=omnichannel_close_conversation,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="workspaceId", label="Workspace", type="omnichannelWorkspace", required=True),
                NodeField(
                    key="closeReasonId", label="Close reason", type="omnichannelCloseReason", required=True
                ),
                NodeField(key="note", label="Note", type="textarea", mergeable=True),
            ],
            outputs=[NodeOutput("status", "Status"), NodeOutput("closeReasonId", "Close reason id")],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.add_comment",
            label="Add comment",
            description="Write an internal note on the conversation (not sent to the contact).",
            icon="MessageSquareText",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_add_comment,
            fields=[
                NodeField(key="contactId", label="Contact", type="text", required=True, mergeable=True),
                NodeField(key="body", label="Comment", type="textarea", required=True, mergeable=True),
            ],
            outputs=[NodeOutput("messageId", "Message id")],
        )
    )
