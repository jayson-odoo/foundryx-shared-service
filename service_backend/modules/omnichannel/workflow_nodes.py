"""Omnichannel workflow-engine node registration (plan sprint-4/17).

Called from ``bootstrap.py::register_engine_entities()`` - the existing,
already-wired module boot hook (``app/module_loader.py::register_module_boot``)
- so this module never needs a core file to import it directly (module
governance: hook via the predefined seam, no global-store injection).
"""
from app.workflow_engine.registry import ActionDef, NodeField, NodeOutput, TriggerDef, register_action, register_trigger

from .services.workflow_actions import omnichannel_get_contact, omnichannel_send_message
from .services.workflow_test_data import build_test_payload, test_metadata

MODULE_NAME = "omnichannel"

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
            ),
            writable=frozenset(
                {"first_name", "last_name", "email", "language", "country_code", "priority"}
            ),
            has_status=False,
            status_attr="lifecycle_status_id",
            module=MODULE_NAME,
            apply_update=_contact_apply_update,
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
                )
            ],
            outputs=_TRIGGER_OUTPUTS,
        )
    )
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
            description="Send a text reply into the triggering conversation.",
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
                NodeField(
                    key="message",
                    label="Message",
                    type="textarea",
                    required=True,
                    mergeable=True,
                ),
            ],
            outputs=[
                NodeOutput("messageId", "Message id"),
                NodeOutput("status", "Send status"),
            ],
        )
    )
