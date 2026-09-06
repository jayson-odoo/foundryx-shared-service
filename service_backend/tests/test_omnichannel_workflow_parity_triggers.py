"""Plan sprint-4/31 (A5a) S1 - omnichannel workflow-parity triggers, registry-
driven dispatch generalization, and "trigger once per contact". Covers
AC-WFP-07..22.

Reuses the existing omnichannel/workflow test seams (`_seed_thread`,
`_channel_id`, `_process`, `_wa_payload`) rather than duplicating fixtures.
"""
from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID, User
from app.models.workflow import RUN_SUCCESS, Workflow, WorkflowRun, WorkflowVersion
from app.services.tenant_service import TenantService
from app.services.workflow_service import WorkflowService
from app.workflow_engine.entity_events import (
    CodeNotAuthorized,
    _match_and_enqueue,
    _trigger_types_for,
    create_run_for_event,
)
from app.workflow_engine.registry import get_trigger
from app.workflow_engine.schemas import WorkflowValidationError
from tests.conftest import ACTIVE_EMAIL
from tests.test_code_workflow_action import FakeRunner
from tests.test_omnichannel_conversations import _seed_thread
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload


def _actor(db, email=ACTIVE_EMAIL) -> User:
    return db.query(User).filter(User.email == email).one()


def _publish(db, trigger_type: str, trigger_config: dict) -> Workflow:
    """A minimal one-trigger-one-action workflow: the action merely loads the
    triggering contact, so a run's existence/context is enough to prove the
    trigger fired (mirrors `test_omnichannel_workflow_triggers.py`'s shape)."""
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": trigger_type, "config": trigger_config},
            {
                "id": "get_1",
                "kind": "action",
                "type": "omnichannel.get_contact",
                "config": {"contactId": "{{ trigger.contact.id }}"},
            },
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "get_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name=f"WFP {trigger_type}", description="", draft=doc, actor_id=None
    )
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    db.refresh(wf)
    return wf


def _runs_for(db, wf_id):
    return db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wf_id).all()


# ── AC-WFP-07: registry-driven dispatch generalization ──────────────────────
def test_trigger_types_for_is_registry_driven(session_factory):
    # Core hardcoded mapping is unchanged.
    assert _trigger_types_for("created") == ["entity.created"]
    assert _trigger_types_for("deleted") == ["entity.deleted"]
    assert set(_trigger_types_for("updated")) >= {
        "entity.updated",
        "entity.field_changed",
        "omnichannel.contact_tag_added",
        "omnichannel.contact_tag_removed",
        "omnichannel.contact_field_changed",
    }
    assert set(_trigger_types_for("status_changed")) >= {
        "entity.status_changed",
        "omnichannel.lifecycle_changed",
    }
    # form.submitted / omnichannel.message_received resolve PURELY from the
    # registry now (their old hardcoded branches are gone).
    assert _trigger_types_for("submitted") == ["form.submitted"]
    assert _trigger_types_for("received") == ["omnichannel.message_received"]
    assert _trigger_types_for("conversation_opened") == ["omnichannel.conversation_opened"]
    assert _trigger_types_for("conversation_closed") == ["omnichannel.conversation_closed"]
    assert _trigger_types_for("conversation_assigned") == ["omnichannel.conversation_assigned"]
    assert _trigger_types_for("completed") == ["omnichannel.broadcast_completed"]

    for key in (
        "omnichannel.conversation_opened",
        "omnichannel.conversation_closed",
        "omnichannel.conversation_assigned",
        "omnichannel.contact_tag_added",
        "omnichannel.contact_tag_removed",
        "omnichannel.contact_field_changed",
        "omnichannel.lifecycle_changed",
        "omnichannel.broadcast_completed",
        "omnichannel.message_received",
    ):
        trig = get_trigger(key)
        assert trig is not None, key


# ── AC-WFP-08: conversation_opened (new thread + reopen) ────────────────────
def test_conversation_opened_fires_for_new_thread_and_reopen(session_factory):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_opened", {})
        wf_id = wf.id
    finally:
        db.close()

    # New contact's very first message -> opened, isReopen False.
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.op-1", from_="60111000111", text="hi"))
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].status == RUN_SUCCESS
        assert runs[0].trigger_payload_json["eventData"]["isReopen"] is False
        assert runs[0].trigger_payload_json["eventData"]["channelId"] == channel_id
    finally:
        db.close()

    # Close then a fresh inbound reopens it -> a SECOND run, isReopen True.
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.conversation_service import ConversationService

    db = session_factory()
    try:
        cid = db.query(Contact).filter(Contact.phone == "+60111000111").first().id
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.op-2", from_="60111000111", text="back"))
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 2
        assert runs[1].trigger_payload_json["eventData"]["isReopen"] is True
        ctx_contact = runs[1].trigger_payload_json.get("recordId")
        assert ctx_contact is not None
    finally:
        db.close()


# ── SF-1 (review round 1): trigger.channelId resolves on every "opened"
# path, not only inbound ────────────────────────────────────────────────────
def test_conversation_opened_channel_id_resolves_on_manual_reopen(session_factory):
    """`patch_thread`'s manual reopen (no inbound message, no `channel_id`
    threaded in) must still carry `trigger.channelId` - resolved from the
    contact's most recent channel-bound message - so an
    `omnichannel.conversation_opened` trigger CONFIGURED with a Channel
    filter fires on a manual reopen too."""
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.sf1-1", from_="60111000199", text="hi"))

    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.conversation_service import ConversationService

    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_opened", {"channelId": channel_id})
        wf_id = wf.id
        cid = db.query(Contact).filter(Contact.phone == "+60111000199").first().id
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()

    db = session_factory()
    try:
        # Manual reopen - no inbound message, no channel_id passed in.
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="OPEN")
    finally:
        db.close()

    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].trigger_payload_json["eventData"]["isReopen"] is True
        assert runs[0].trigger_payload_json["eventData"]["channelId"] == channel_id
    finally:
        db.close()


# ── AC-WFP-38: Logs shows the trigger node's captured event data ───────────
def test_conversation_opened_trigger_node_captures_event_data_in_logs(session_factory):
    """The trigger node's `WorkflowRunNode.output_json` is reconstructed
    generically from the flat `trigger.*` run context (plan 31 S3) - no
    per-trigger hardcoded block, and it must never crash even though some
    rule-engine record facts (e.g. a date fact's `.daysSince`/`.daysUntil`)
    are BOTH a leaf value and a parent of derived sub-facts."""
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_opened", {})
        wf_id = wf.id
    finally:
        db.close()

    _process(session_factory, channel_id, _wa_payload(wamid="wamid.trace-1", from_="60111000112", text="hi"))
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].status == RUN_SUCCESS
        trigger_node = next(
            n for n in runs[0].nodes if n.node_type == "omnichannel.conversation_opened"
        )
        output = trigger_node.output_json
        assert output["contact"]["phone"] == "+60111000112"
        assert output["conversationId"]
        assert output["workspaceId"]
        assert output["isReopen"] is False
        assert output["channelId"] == channel_id
        # The rule-engine fact surface is a SEPARATE picker group - excluded
        # from the trigger's own captured-event output (and the very source
        # of the leaf/branch collision this test guards against).
        assert "record" not in output
    finally:
        db.close()


def test_workflow_trigger_child_run_trigger_node_captures_chain_context(session_factory):
    """A `workflow.trigger`-started child run's trigger node exposes
    `source`/`parentRunId`/`contactId` (plan 31 S3, AC-WFP-38) - the SAME
    generic reconstruction that omnichannel triggers use, proving it is not
    an omnichannel-only special case."""
    from app.workflow_engine.actions.workflow_trigger_actions import workflow_trigger
    from app.workflow_engine.executor import _ctx_from_payload

    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        child_wf = _publish(db, "manual", {})
        child_id = child_wf.id
        parent_run = WorkflowRun(
            id="run-parent-1",
            workflow_id="wf-parent-1",
            version_id=None,
            version_number=0,
            status=RUN_SUCCESS,
            triggered_by="event",
            tenant_id=DEFAULT_TENANT_ID,
            trigger_payload_json={},
            definition_snapshot_json={"schemaVersion": 2, "nodes": [], "edges": []},
            depth=0,
        )
        db.add(parent_run)
        db.commit()
        parent_run_id = parent_run.id
        ctx = {"_workflow.runId": parent_run_id, "_workflow.workflowId": "wf-parent-1"}
        result = workflow_trigger(db, DEFAULT_TENANT_ID, {"workflowId": child_id}, ctx)
        child_run_id = result["runId"]
    finally:
        db.close()

    db = session_factory()
    try:
        child_run = db.query(WorkflowRun).filter(WorkflowRun.id == child_run_id).one()
        child_ctx = _ctx_from_payload(child_run.trigger_payload_json)
        assert child_ctx["trigger.source"] == "workflow"
        assert child_ctx["trigger.parentRunId"] == parent_run_id
        trigger_node = next(n for n in child_run.nodes if n.node_type == "manual")
        output = trigger_node.output_json
        assert output["source"] == "workflow"
        assert output["parentRunId"] == parent_run_id
    finally:
        db.close()


def test_conversation_opened_reopen_only_filter(session_factory):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_opened", {"reopenOnly": True})
        wf_id = wf.id
    finally:
        db.close()
    # Brand-new thread does NOT match "reopen only".
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.ro-1", from_="60111000112", text="hi"))
    db = session_factory()
    try:
        assert _runs_for(db, wf_id) == []
    finally:
        db.close()


# ── AC-WFP-09: conversation_closed (+ close-reason filter) ──────────────────
def test_conversation_closed_fires_and_filters_by_reason(session_factory):
    from modules.omnichannel.models import CloseReason, Workspace
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    reason = CloseReason(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name="Resolved")
    other_reason = CloseReason(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name="Spam")
    db.add_all([reason, other_reason])
    db.commit()
    reason_id, other_reason_id = reason.id, other_reason.id
    db.close()

    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {"closeReasonId": reason_id})
        wf_id = wf.id
    finally:
        db.close()

    # Closing with the OTHER reason does not match.
    db = session_factory()
    try:
        ConversationService(db).close_thread(
            cid, DEFAULT_TENANT_ID, close_reason_id=other_reason_id, note="nope"
        )
    finally:
        db.close()
    db = session_factory()
    try:
        assert _runs_for(db, wf_id) == []
    finally:
        db.close()

    # Reopen, close with the CONFIGURED reason -> fires with context.
    db = session_factory()
    try:
        svc = ConversationService(db)
        svc.patch_thread(cid, DEFAULT_TENANT_ID, status="OPEN")
        svc.close_thread(cid, DEFAULT_TENANT_ID, close_reason_id=reason_id, note="all good")
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        data = runs[0].trigger_payload_json["eventData"]
        assert data["closeReasonId"] == reason_id
        assert data["closeReasonLabel"] == "Resolved"
        assert data["note"] == "all good"
    finally:
        db.close()


def test_conversation_closed_unset_reason_fires_for_any_close(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {})
        wf_id = wf.id
    finally:
        db.close()
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_id)) == 1
    finally:
        db.close()


# ── AC-WFP-10: conversation_assigned (assign / reassign / unassign) ─────────
def test_conversation_assigned_fires_and_no_op_writes_nothing(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    admin_id = _actor(db).id
    try:
        wf = _publish(db, "omnichannel.conversation_assigned", {})
        wf_id = wf.id
    finally:
        db.close()

    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, assigned_user_id=admin_id)
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        data = runs[0].trigger_payload_json["eventData"]
        assert data["assigneeUserId"] == admin_id
        assert data["previousAssigneeUserId"] is None
        assert data["assignedVia"] == "manual"
    finally:
        db.close()

    # Re-sending the SAME assignee is a no-op at the event-write layer -> no
    # second run.
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, assigned_user_id=admin_id)
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_id)) == 1
    finally:
        db.close()

    # Unassign -> a SECOND run, assigneeUserId null.
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, assigned_user_id=None)
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 2
        data = runs[1].trigger_payload_json["eventData"]
        assert data["assigneeUserId"] is None
        assert data["previousAssigneeUserId"] == admin_id
    finally:
        db.close()


def test_conversation_assigned_on_unassign_filter(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    admin_id = _actor(db).id
    try:
        wf = _publish(db, "omnichannel.conversation_assigned", {"onUnassign": True})
        wf_id = wf.id
    finally:
        db.close()
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, assigned_user_id=admin_id)
    finally:
        db.close()
    db = session_factory()
    try:
        assert _runs_for(db, wf_id) == []  # a plain assign does not match "only on unassign"
    finally:
        db.close()
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, assigned_user_id=None)
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_id)) == 1
    finally:
        db.close()


# ── AC-WFP-11: contact_tag_added / contact_tag_removed ──────────────────────
def test_contact_tag_added_and_removed_refine_by_tag(session_factory):
    from modules.omnichannel.models import Contact, ContactTag, Workspace
    from modules.omnichannel.services.contact_profile_service import ContactProfileService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    tag_a = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name="VIP")
    tag_b = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name="Spam")
    db.add_all([tag_a, tag_b])
    db.commit()
    tag_a_id, tag_b_id = tag_a.id, tag_b.id
    db.close()

    db = session_factory()
    try:
        wf_added = _publish(db, "omnichannel.contact_tag_added", {"tagId": tag_a_id})
        wf_removed = _publish(db, "omnichannel.contact_tag_removed", {"tagId": tag_a_id})
        added_id, removed_id = wf_added.id, wf_removed.id
    finally:
        db.close()

    # Add the OTHER tag first - neither trigger matches (wrong tag).
    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, tag_ids=[tag_b_id])
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        assert _runs_for(db, added_id) == []
        assert _runs_for(db, removed_id) == []
    finally:
        db.close()

    # Add the CONFIGURED tag -> contact_tag_added fires, tagName resolved.
    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, tag_ids=[tag_a_id, tag_b_id])
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, added_id)
        assert len(runs) == 1
        data = runs[0].trigger_payload_json["eventData"]
        assert data["tagId"] == tag_a_id
        assert data["tagName"] == "VIP"
        assert _runs_for(db, removed_id) == []
    finally:
        db.close()

    # Remove the CONFIGURED tag -> contact_tag_removed fires.
    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, tag_ids=[tag_b_id])
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, removed_id)
        assert len(runs) == 1
        assert runs[0].trigger_payload_json["eventData"]["tagId"] == tag_a_id
    finally:
        db.close()


# ── AC-WFP-12: contact_field_changed ─────────────────────────────────────────
def test_contact_field_changed_refines_by_key_and_value(session_factory):
    from modules.omnichannel.models import Contact, ContactField, Workspace
    from modules.omnichannel.services.contact_profile_service import ContactProfileService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    field = ContactField(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, key="plan", label="Plan", type="text"
    )
    db.add(field)
    db.commit()
    db.close()

    db = session_factory()
    try:
        wf_any = _publish(db, "omnichannel.contact_field_changed", {"fieldKey": "plan"})
        wf_val = _publish(
            db, "omnichannel.contact_field_changed", {"fieldKey": "plan", "newValue": "pro"}
        )
        any_id, val_id = wf_any.id, wf_val.id
    finally:
        db.close()

    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, custom_fields={"plan": "basic"})
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, any_id)) == 1
        assert _runs_for(db, val_id) == []  # value filter doesn't match "basic"
        data = _runs_for(db, any_id)[0].trigger_payload_json["eventData"]
        assert data["fieldKey"] == "plan"
        assert data["fromValue"] is None
        assert data["toValue"] == "basic"
    finally:
        db.close()

    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, custom_fields={"plan": "pro"})
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, any_id)) == 2
        assert len(_runs_for(db, val_id)) == 1
    finally:
        db.close()


# ── AC-WFP-13: lifecycle_changed rides the SAME status_changed emission ─────
def test_lifecycle_changed_and_generic_status_changed_both_fire(session_factory):
    from app.workflow_engine.entities import WorkflowEntity, register_workflow_entity
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services import lifecycle_service

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    contact = db.query(Contact).filter(Contact.id == cid).first()
    contact.lifecycle_status_id = lifecycle_service.initial_status_id(db, DEFAULT_TENANT_ID, ws_id)
    db.commit()
    db.close()

    db = session_factory()
    try:
        from app.status_engine import registry as status_registry

        moves = status_registry  # noqa: F401 - not used, keeps import local/lazy-safe
        wf_lifecycle = _publish(db, "omnichannel.lifecycle_changed", {})
        # A generic entity.status_changed workflow on the SAME entity - proves
        # the machine's ONE emission still serves both trigger types.
        doc = {
            "schemaVersion": 2,
            "nodes": [
                {
                    "id": "trg",
                    "kind": "trigger",
                    "type": "entity.status_changed",
                    "config": {"entityType": "omnichannel_contact"},
                },
                {
                    "id": "get_1",
                    "kind": "action",
                    "type": "omnichannel.get_contact",
                    "config": {"contactId": "{{ trigger.record.id }}"},
                },
            ],
            "edges": [{"id": "e1", "source": "trg", "target": "get_1"}],
        }
        service = WorkflowService(db)
        wf_generic = service.create(
            DEFAULT_TENANT_ID, name="generic status", description="", draft=doc, actor_id=None
        )
        service.set_active(wf_generic.id, DEFAULT_TENANT_ID, True)
        service.publish(wf_generic.id, DEFAULT_TENANT_ID, actor_id=None)
        lifecycle_id, generic_id = wf_lifecycle.id, wf_generic.id
    finally:
        db.close()

    db = session_factory()
    try:
        from modules.omnichannel.services import lifecycle_service as ls

        moves = ls.fireable_moves(db, db.query(Contact).filter(Contact.id == cid).first())
        assert moves
        target = moves[0].to_status_id
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ls.move(db, contact, target)
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        assert len(_runs_for(db, lifecycle_id)) == 1
        assert len(_runs_for(db, generic_id)) == 1
    finally:
        db.close()


# ── SF-6 (plan 31 S3 review): `trigger.toStageLabel` is actually populated ──
def test_lifecycle_changed_populates_to_stage_label(session_factory):
    """`omnichannel.lifecycle_changed` advertises `trigger.toStageLabel` as a
    `NodeOutput` - it must not always render empty (foolproof-UI)."""
    from app.models.status import Status as CoreStatus
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services import lifecycle_service

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    contact = db.query(Contact).filter(Contact.id == cid).first()
    contact.lifecycle_status_id = lifecycle_service.initial_status_id(db, DEFAULT_TENANT_ID, ws_id)
    db.commit()
    db.close()

    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.lifecycle_changed", {})
        wf_id = wf.id
    finally:
        db.close()

    db = session_factory()
    try:
        moves = lifecycle_service.fireable_moves(db, db.query(Contact).filter(Contact.id == cid).first())
        assert moves
        target_id = moves[0].to_status_id
        target_label = (
            db.query(CoreStatus.label).filter(CoreStatus.id == target_id).scalar()
        )
        contact = db.query(Contact).filter(Contact.id == cid).first()
        lifecycle_service.move(db, contact, target_id)
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].trigger_payload_json["eventData"]["toStageLabel"] == target_label
        assert target_label is not None
    finally:
        db.close()


# ── AC-WFP-14: message_received filters (firstMessageOnly, keywordContains) ─
def test_message_received_first_message_and_keyword_filters(session_factory):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf_first = _publish(db, "omnichannel.message_received", {"firstMessageOnly": True})
        wf_keyword = _publish(db, "omnichannel.message_received", {"keywordContains": "refund"})
        first_id, keyword_id = wf_first.id, wf_keyword.id
    finally:
        db.close()

    _process(
        session_factory, channel_id,
        _wa_payload(wamid="wamid.fm-1", from_="60111000199", text="I want a REFUND please"),
    )
    db = session_factory()
    try:
        assert len(_runs_for(db, first_id)) == 1  # brand new contact -> first message
        assert len(_runs_for(db, keyword_id)) == 1  # case-insensitive substring
    finally:
        db.close()

    # A second message from the SAME contact - not first, no keyword.
    _process(
        session_factory, channel_id,
        _wa_payload(wamid="wamid.fm-2", from_="60111000199", text="thanks"),
    )
    db = session_factory()
    try:
        assert len(_runs_for(db, first_id)) == 1
        assert len(_runs_for(db, keyword_id)) == 1
    finally:
        db.close()


# ── AC-WFP-15: "trigger once per contact" ────────────────────────────────────
def test_trigger_once_per_contact_claims_once_per_workflow(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid_a = _seed_thread(session_factory, name="Contact A", phone="+60111000201", messages=[{"body": "hi"}])
    cid_b = _seed_thread(session_factory, name="Contact B", phone="+60111000202", messages=[{"body": "hi"}])

    db = session_factory()
    try:
        wf_a = _publish(db, "omnichannel.conversation_closed", {"triggerOncePerContact": True})
        wf_b = _publish(db, "omnichannel.conversation_closed", {})  # no once-flag, control
        wf_a_id, wf_b_id = wf_a.id, wf_b.id
    finally:
        db.close()

    db = session_factory()
    try:
        svc = ConversationService(db)
        svc.patch_thread(cid_a, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_a_id)) == 1
        assert len(_runs_for(db, wf_b_id)) == 1
    finally:
        db.close()

    # Reopen + close AGAIN for the SAME contact -> wf_a (once-flagged) gets NO
    # second run; wf_b (unflagged control) DOES.
    db = session_factory()
    try:
        svc = ConversationService(db)
        svc.patch_thread(cid_a, DEFAULT_TENANT_ID, status="OPEN")
        svc.patch_thread(cid_a, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_a_id)) == 1
        assert len(_runs_for(db, wf_b_id)) == 2
    finally:
        db.close()

    # A DIFFERENT contact still fires the once-flagged workflow (the claim is
    # per contact, not global).
    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid_b, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()
    db = session_factory()
    try:
        assert len(_runs_for(db, wf_a_id)) == 2
    finally:
        db.close()


def test_trigger_once_per_contact_concurrent_duplicate_skips_silently(session_factory):
    from modules.omnichannel.services.workflow_fire_store import claim_fire

    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {"triggerOncePerContact": True})
        assert claim_fire(db, tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, contact_id="cnt-race") is True
        # A second, concurrent claim for the SAME (tenant, workflow, contact)
        # loses the unique-constraint race - no exception escapes, no crash.
        assert claim_fire(db, tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, contact_id="cnt-race") is False
        db.commit()
    finally:
        db.close()


def test_trigger_once_per_contact_marker_survives_republish_deleted_with_workflow(session_factory):
    from modules.omnichannel.models import WorkflowContactFire
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {"triggerOncePerContact": True})
        wf_id = wf.id
    finally:
        db.close()

    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()

    db = session_factory()
    try:
        assert (
            db.query(WorkflowContactFire)
            .filter(WorkflowContactFire.workflow_id == wf_id, WorkflowContactFire.contact_id == cid)
            .count()
            == 1
        )
        # Republish (unpublish + publish again) - the marker is untouched.
        service = WorkflowService(db)
        service.unpublish(wf_id, DEFAULT_TENANT_ID)
        service.publish(wf_id, DEFAULT_TENANT_ID, actor_id=None)
    finally:
        db.close()
    db = session_factory()
    try:
        assert (
            db.query(WorkflowContactFire).filter(WorkflowContactFire.workflow_id == wf_id).count() == 1
        )
        # Permanently delete the workflow -> its markers are deleted with it.
        WorkflowService(db).remove(wf_id, DEFAULT_TENANT_ID)
    finally:
        db.close()
    db = session_factory()
    try:
        assert (
            db.query(WorkflowContactFire).filter(WorkflowContactFire.workflow_id == wf_id).count() == 0
        )
    finally:
        db.close()


# ── nit (plan 31 S3 review): a CodeNotAuthorized skip releases the winning
# once-per-contact claim instead of burning it with no run ever produced ────
def test_trigger_once_per_contact_claim_released_on_code_not_authorized_skip(session_factory):
    from app.workflow_engine.code_runner import use_code_runner_client
    from modules.omnichannel.models import WorkflowContactFire
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {
                "id": "trg", "kind": "trigger", "type": "omnichannel.conversation_closed",
                "config": {"triggerOncePerContact": True},
            },
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name="WFP-once code-skip", description="", draft=doc,
        actor_id=admin.id, actor=admin,
    )
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None  # simulate a tampered/legacy stamp
    db.commit()
    wf_id = wf.id
    db.close()

    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()

    db = session_factory()
    try:
        assert _runs_for(db, wf_id) == []  # the skip never produced a run ...
        # ... and the claim it took was RELEASED, not burned permanently.
        assert (
            db.query(WorkflowContactFire)
            .filter(WorkflowContactFire.workflow_id == wf_id, WorkflowContactFire.contact_id == cid)
            .count()
            == 0
        )
    finally:
        db.close()


# ── AC-WFP-16: tenant isolation ──────────────────────────────────────────────
def test_tenant_isolation_cross_tenant_event_never_matches(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {})
        wf_id = wf.id
        other_tenant_id = TenantService(db).provision(
            name="WFP Other", slug="wfp-other-t16", admin_email="wfp-other-t16@example.com",
            admin_name="Admin", admin_password="Password123!",
        ).id
    finally:
        db.close()

    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services import statuses

    db = session_factory()
    try:
        ws = Workspace(tenant_id=other_tenant_id, name="Other WS", is_default=True)
        db.add(ws)
        db.flush()
        other_contact = Contact(
            tenant_id=other_tenant_id,
            workspace_id=ws.id,
            phone="+60199999999",
            status_id=statuses.status_id_for(db, other_tenant_id, "THREAD", "OPEN"),
            priority="MEDIUM",
        )
        db.add(other_contact)
        db.commit()
        other_cid = other_contact.id
    finally:
        db.close()

    db = session_factory()
    try:
        ConversationService(db).patch_thread(other_cid, other_tenant_id, status="CLOSED")
    finally:
        db.close()
    db = session_factory()
    try:
        assert _runs_for(db, wf_id) == []  # tenant A's workflow never sees tenant B's event
    finally:
        db.close()


# ── AC-WFP-17: emission failure never breaks the triggering request ─────────
def test_emission_failure_never_breaks_the_request(session_factory, monkeypatch):
    from modules.omnichannel.services import event_service
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.workflow_engine.entity_events.emit_entity_event", _boom)
    db = session_factory()
    try:
        # Would raise if `_emit_workflow_event`'s try/except didn't isolate it.
        item = ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
        assert item is not None
    finally:
        db.close()


# ── AC-WFP-18: origin-chain loop guard is inherited, not re-implemented ─────
def test_loop_guard_inherited_for_new_trigger_types(session_factory):
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_closed", {})
        # A synthetic event whose origin chain already contains THIS workflow -
        # the shared `_origin_chain`/`chain` guard must skip it, matching the
        # existing entity.* behaviour (no re-implementation for this trigger).
        fake_run = WorkflowRun(
            tenant_id=DEFAULT_TENANT_ID, workflow_id=wf.id, version_id=wf.current_version_id,
            version_number=1, status=RUN_SUCCESS, triggered_by="event",
            definition_snapshot_json={"schemaVersion": 2, "nodes": [], "edges": []},
            trigger_payload_json={},
        )
        db.add(fake_run)
        db.flush()
        ev = {
            "entity_type": "omnichannel_contact", "action": "conversation_closed",
            "tenant_id": DEFAULT_TENANT_ID, "record_id": "cnt-loop", "actor": None,
            "changes": None, "extra": {}, "record_facts": {},
            "source": {"run_id": fake_run.id, "workflow_id": wf.id, "depth": 0},
        }
        _match_and_enqueue(db, ev)
        db.commit()
        assert _runs_for(db, wf.id) == [fake_run]  # no new run created
    finally:
        db.close()


# ── AC-WFP-19: unauthorized Code node fails closed (inherited gate) ─────────
def test_unauthorized_code_node_creates_no_run_for_new_trigger(session_factory):
    from app.workflow_engine.code_runner import use_code_runner_client

    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "omnichannel.conversation_closed", "config": {}},
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name="WFP unauthorized code", description="", draft=doc,
        actor_id=admin.id, actor=admin,
    )
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None  # simulate a tampered/legacy stamp
    db.commit()

    ev = {
        "entity_type": "omnichannel_contact", "action": "conversation_closed",
        "tenant_id": DEFAULT_TENANT_ID, "record_id": "cnt-x", "actor": None,
        "changes": None, "extra": {}, "record_facts": {}, "source": None,
    }
    with pytest.raises(CodeNotAuthorized):
        create_run_for_event(db, wf, ev, depth=0)
    assert _runs_for(db, wf.id) == []
    db.close()


# ── AC-WFP-20: publish denormalization, unpublish clears it ─────────────────
def test_publish_denormalizes_trigger_entity_type_unpublish_clears(session_factory):
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.conversation_opened", {})
        db.refresh(wf)
        assert wf.trigger_type == "omnichannel.conversation_opened"
        assert wf.trigger_entity_type == "omnichannel_contact"
        WorkflowService(db).unpublish(wf.id, DEFAULT_TENANT_ID)
        db.refresh(wf)
        assert wf.trigger_type is None
        assert wf.trigger_entity_type is None
    finally:
        db.close()


# ── AC-WFP-21: GET /workflows/metadata omnichannelWorkspaces ────────────────
def test_metadata_returns_omnichannel_workspaces(session_factory):
    from modules.omnichannel.models import CloseReason, ContactField, ContactTag, Workspace
    from modules.omnichannel.services import lifecycle_service
    from app.models.status import Status as CoreStatus

    db = session_factory()
    try:
        ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
        db.add(ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="VIP"))
        db.add(ContactField(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, key="plan", label="Plan", type="text"))
        db.add(CloseReason(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Resolved"))
        db.add(
            CoreStatus(
                tenant_id=DEFAULT_TENANT_ID,
                entity_type=lifecycle_service.ENTITY_TYPE,
                scope_id=ws.id,
                key="qualified",
                label="Qualified",
                color="#000000",
                sort_order=0,
            )
        )
        db.commit()
        metadata = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
        assert "omnichannelWorkspaces" in metadata
        found = next(w for w in metadata["omnichannelWorkspaces"] if w["id"] == ws.id)
        assert any(t["name"] == "VIP" for t in found["contactTags"])
        assert any(f["key"] == "plan" and f["type"] == "text" for f in found["contactFields"])
        assert any(r["name"] == "Resolved" for r in found["closeReasons"])
        # `name` (not `label`) - matches the sibling arrays + the frontend
        # `WorkflowOmnichannelWorkspace.lifecycleStages` contract (S3 drift fix).
        assert any(s["name"] == "Qualified" for s in found["lifecycleStages"])
        assert "members" in found
    finally:
        db.close()


# ── B-1 (review round 1) parity guard: backend<->FE metadata key shape ─────
def test_omnichannel_workspace_options_key_shape_matches_frontend_type(session_factory):
    """Plan 31 S3 review B-1: the review's root cause was a backend<->FE
    field-shape drift (the wire never carried `closeReasons[].isActive`, but
    the FE type/filter assumed it did) that silently emptied a whole picker.
    Pin every array's dict-key SET exactly against
    `WorkflowOmnichannelWorkspace` (types/workflows.ts) - this is the backend
    half of the parity pair; `types/workflows.parity.test.ts` is the frontend
    half. A field added/removed on either side without the other must fail
    ONE of these two tests, loudly, instead of silently breaking a node."""
    from modules.omnichannel.models import (
        Channel, CloseReason, ContactField, ContactTag, Workspace, WhatsappTemplate, WorkspaceMember,
    )
    from modules.omnichannel.services import lifecycle_service
    from app.models.status import Status as CoreStatus

    db = session_factory()
    try:
        ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
        admin = _actor(db)
        channel = Channel(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Parity Channel")
        db.add(channel)
        db.flush()
        db.add(ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="VIP"))
        db.add(ContactField(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, key="plan", label="Plan", type="text"))
        db.add(CloseReason(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Resolved"))
        existing_member = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == admin.id)
            .first()
        )
        if existing_member is None:
            db.add(WorkspaceMember(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, user_id=admin.id))
        db.add(
            WhatsappTemplate(
                tenant_id=DEFAULT_TENANT_ID, channel_id=channel.id,
                name="welcome_message", status="approved",
            )
        )
        db.add(
            CoreStatus(
                tenant_id=DEFAULT_TENANT_ID,
                entity_type=lifecycle_service.ENTITY_TYPE,
                scope_id=ws.id,
                key="wfp-b1-parity",
                label="Qualified",
                color="#000000",
                sort_order=0,
            )
        )
        db.commit()
        metadata = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
        found = next(w for w in metadata["omnichannelWorkspaces"] if w["id"] == ws.id)
        assert set(found["contactTags"][0].keys()) == {"id", "name"}
        assert set(found["contactFields"][0].keys()) == {"key", "label", "type"}
        assert set(found["lifecycleStages"][0].keys()) == {"id", "name"}
        # The load-bearing assertion - NO `isActive` key (B-1).
        assert set(found["closeReasons"][0].keys()) == {"id", "name"}
        assert set(found["members"][0].keys()) == {"id", "name", "email"}
        assert set(found["templates"][0].keys()) == {"id", "name", "status"}
    finally:
        db.close()


# ── B-2 (review round 1): metadata members picker never leaks another
# tenant's user by name/email; SF-7: a trashed user is never offered either ──
def test_metadata_members_excludes_foreign_tenant_and_trashed_users(session_factory):
    from modules.omnichannel.models import Workspace, WorkspaceMember

    other_tenant_id = None
    db = session_factory()
    try:
        other_tenant_id = TenantService(db).provision(
            name="WFP Members Other", slug="wfp-members-other",
            admin_email="wfp-members-other@example.com",
            admin_name="Other Admin", admin_password="Password123!",
        ).id
    finally:
        db.close()

    db = session_factory()
    try:
        ws = db.query(Workspace).filter(
            Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)
        ).first()
        other_user = db.query(User).filter(User.tenant_id == other_tenant_id).one()

        trashed_user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email="wfp-trashed-member@example.com",
            name="Trashed Member",
            password="x",
            is_trashed=True,
        )
        db.add(trashed_user)
        db.flush()

        # A stored (polymorphic) member id planted straight in the table - the
        # exact shape a leaked/forged id would take (B-2 - the members query
        # must resolve `WorkspaceMember.user_id` tenant-scoped, never bare).
        db.add(WorkspaceMember(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, user_id=other_user.id))
        db.add(WorkspaceMember(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, user_id=trashed_user.id))
        db.commit()

        metadata = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
        found = next(w for w in metadata["omnichannelWorkspaces"] if w["id"] == ws.id)
        member_ids = {m["id"] for m in found["members"]}
        member_names = {m["name"] for m in found["members"]}
        member_emails = {m.get("email") for m in found["members"]}
        assert other_user.id not in member_ids
        assert other_user.email not in member_emails
        assert other_user.name not in member_names
        assert trashed_user.id not in member_ids
        assert trashed_user.name not in member_names
    finally:
        db.close()


# ── plan 31 S3 review B-4: registeredNodeTypes gates the palette ───────────
def test_metadata_registered_node_types_lists_every_registered_trigger_and_action(session_factory):
    """The frontend catalog filters itself to this list (B-4) so an
    unregistered node type (ask_question/wait/business_hours/http.request -
    S4/S5) is never offered before its backend ActionDef/TriggerDef lands."""
    db = session_factory()
    try:
        metadata = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
        assert "registeredNodeTypes" in metadata
        registered = set(metadata["registeredNodeTypes"])
        # Registered (S1/S2) - must be present.
        for key in (
            "omnichannel.conversation_opened",
            "omnichannel.conversation_closed",
            "omnichannel.message_received",
            "omnichannel.assign_conversation",
            "omnichannel.add_tag",
            "omnichannel.update_lifecycle",
            "omnichannel.send_message",
            "workflow.trigger",
            "manual",
        ):
            assert key in registered, f"{key} missing from registeredNodeTypes"
        # NOT registered until S4/S5 - must be ABSENT.
        for key in (
            "omnichannel.ask_question",
            "omnichannel.wait",
            "omnichannel.business_hours",
            "http.request",
        ):
            assert key not in registered, f"{key} should not be registered yet (S4/S5)"
    finally:
        db.close()


# ── AC-WFP-22: broadcast_completed (A4 not merged - synthetic emission) ─────
def test_broadcast_completed_registered_and_fires_on_synthetic_emission(session_factory):
    db = session_factory()
    try:
        wf = _publish(db, "omnichannel.broadcast_completed", {})
        wf_id = wf.id
        ev = {
            "entity_type": "omnichannel_broadcast", "action": "completed",
            "tenant_id": DEFAULT_TENANT_ID, "record_id": "bc-1", "actor": None,
            "changes": None, "record_facts": {},
            "extra": {"broadcastId": "bc-1", "broadcastName": "Promo", "sent": 10, "failed": 1},
            "source": None,
        }
        _match_and_enqueue(db, ev)
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        data = runs[0].trigger_payload_json["eventData"]
        assert data == {"broadcastId": "bc-1", "broadcastName": "Promo", "sent": 10, "failed": 1}
    finally:
        db.close()


# ── Publish gate: unregistered node type (S0 found this hole) ──────────────
def test_publish_rejects_unregistered_node_type(session_factory):
    from app.workflow_engine.schemas import validate_definition

    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "manual", "config": {}},
            {"id": "a1", "kind": "action", "type": "omnichannel.not_a_real_action", "config": {}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "a1"}],
    }
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(doc)
    assert any("unrecognized node type" in issue for issue in exc.value.issues)
