"""Plan sprint-4/31 (A5a) S2 - omnichannel workflow-parity "simple steps"
(ActionDefs routed through existing services). Covers AC-WFP-23..35.

Reuses the existing omnichannel/workflow test seams (`_seed_thread`,
`_seed_template`, `_channel_id`, `_auth`) rather than duplicating fixtures.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.models.workflow import RUN_FAILED, RUN_SUCCESS, Workflow, WorkflowRun
from app.security import hash_password
from app.services.workflow_service import WorkflowService
from app.workflow_engine.schemas import WorkflowValidationError, validate_definition
from modules.omnichannel.services.workflow_actions import (
    ActionError as OmniActionError,
    omnichannel_add_comment,
    omnichannel_add_tag,
    omnichannel_assign_conversation,
    omnichannel_close_conversation,
    omnichannel_open_conversation,
    omnichannel_remove_tag,
    omnichannel_send_message,
    omnichannel_update_field,
    omnichannel_update_lifecycle,
)
from app.workflow_engine.actions.workflow_trigger_actions import (
    ActionError as CoreActionError,
    workflow_trigger,
)
from tests.test_omnichannel_conversations import _seed_template, _seed_thread
from tests.test_omnichannel_workflow_parity_triggers import _publish, _runs_for


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_workspace(db):
    from modules.omnichannel.models import Workspace

    return db.query(Workspace).filter(Workspace.is_default.is_(True)).first()


def _add_member(db, workspace_id, *, email, offset_seconds=0) -> str:
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password("member1234"),
        name=email.split("@")[0],
        status=UserStatus.ACTIVE.value,
        email_verified_at=_now(),
    )
    db.add(user)
    db.flush()
    from modules.omnichannel.models import WorkspaceMember

    db.add(
        WorkspaceMember(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=workspace_id,
            user_id=user.id,
            created_at=_now() - timedelta(seconds=100 - offset_seconds),
        )
    )
    db.flush()
    return user.id


def _add_tag(db, workspace_id, name="VIP") -> str:
    from modules.omnichannel.models import ContactTag

    tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=workspace_id, name=name)
    db.add(tag)
    db.flush()
    return tag.id


def _add_field(db, workspace_id, key="budget", ftype="number") -> str:
    from modules.omnichannel.models import ContactField

    field = ContactField(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        key=key,
        label=key.title(),
        type=ftype,
    )
    db.add(field)
    db.flush()
    return field.key


def _add_close_reason(db, workspace_id, *, name="Resolved", is_active=True) -> str:
    from modules.omnichannel.models import CloseReason

    reason = CloseReason(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=workspace_id, name=name, is_active=is_active
    )
    db.add(reason)
    db.flush()
    return reason.id


# ── AC-WFP-23/24: assign_conversation ───────────────────────────────────────
def test_assign_conversation_user_mode(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        member_id = _add_member(db, ws.id, email="agent1@example.com")
        db.commit()
        out = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "user", "userId": member_id}, {}
        )
        assert out == {"assignedUserId": member_id, "assignedTeamId": None, "assigned": True}
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.assigned_user_id == member_id
    finally:
        db.close()


def test_assign_conversation_unknown_user_fails_and_writes_nothing(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        with pytest.raises(OmniActionError):
            omnichannel_assign_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "user", "userId": "nope"}, {}
            )
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.assigned_user_id is None
    finally:
        db.close()


def test_assign_conversation_round_robin_alternates_and_persists_cursor(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        m1 = _add_member(db, ws.id, email="rr1@example.com", offset_seconds=0)
        m2 = _add_member(db, ws.id, email="rr2@example.com", offset_seconds=1)
        db.commit()

        out1 = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "round_robin"}, {}
        )
        assert out1["assigned"] is True
        first_pick = out1["assignedUserId"]
        assert first_pick == m1  # stable order, no prior cursor -> first eligible

        out2 = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "round_robin"}, {}
        )
        assert out2["assignedUserId"] == m2  # cursor advanced, wraps deterministically

        from modules.omnichannel.models import Workspace

        refreshed = db.query(Workspace).filter(Workspace.id == ws.id).first()
        assert refreshed.round_robin_cursor == m2
    finally:
        db.close()


def test_assign_conversation_round_robin_cursor_not_advanced_on_failed_assign(session_factory, monkeypatch):
    """Plan 31 S3 review nit: the cursor must advance ONLY on a successful
    assign - advancing before `patch_thread` would persist the advance (at
    the run's terminal commit) even though the pick was never assigned."""
    from modules.omnichannel.services.conversation_service import ConversationService, InvalidPatch

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        _add_member(db, ws.id, email="rr-fail1@example.com", offset_seconds=0)
        _add_member(db, ws.id, email="rr-fail2@example.com", offset_seconds=1)
        db.commit()

        def _boom(self, *a, **k):
            raise InvalidPatch("simulated race")

        monkeypatch.setattr(ConversationService, "patch_thread", _boom)
        with pytest.raises(OmniActionError):
            omnichannel_assign_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "round_robin"}, {}
            )

        from modules.omnichannel.models import Workspace

        refreshed = db.query(Workspace).filter(Workspace.id == ws.id).first()
        assert refreshed.round_robin_cursor is None  # NOT advanced to m1
    finally:
        db.close()


def test_assign_conversation_round_robin_empty_roster_succeeds_no_op(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "round_robin"}, {}
        )
        assert out == {"assignedUserId": None, "assignedTeamId": None, "assigned": False}
    finally:
        db.close()


def test_assign_conversation_unassign(session_factory):
    cid = _seed_thread(session_factory, assigned_email="demo@example.com", messages=[])
    db = session_factory()
    try:
        out = omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "unassign"}, {}
        )
        assert out == {"assignedUserId": None, "assignedTeamId": None, "assigned": False}
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.assigned_user_id is None
    finally:
        db.close()


def test_assign_conversation_stamps_workflow_assigned_via(session_factory):
    """AC-WFP-23: writes through `patch_thread` so the emitted
    `conversation_assigned` trigger context reports `assignedVia == "workflow"`
    - the same seam a manual UI assign uses, distinguishable via the kind."""
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        member_id = _add_member(db, ws.id, email="agent2@example.com")
        db.commit()
    finally:
        db.close()

    wf = _publish(session_factory(), "omnichannel.conversation_assigned", {})
    wf_id = wf.id

    db = session_factory()
    try:
        omnichannel_assign_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "mode": "user", "userId": member_id}, {}
        )
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].trigger_payload_json["eventData"]["assignedVia"] == "workflow"
    finally:
        db.close()


# ── AC-WFP-25: add_tag / remove_tag ──────────────────────────────────────────
def test_add_tag_then_idempotent_no_op(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        tag_id = _add_tag(db, ws.id)
        db.commit()

        out = omnichannel_add_tag(db, DEFAULT_TENANT_ID, {"contactId": cid, "tagId": tag_id}, {})
        assert out == {"tags": [tag_id], "changed": True}

        # A second add of the SAME tag is a successful no-op (no change event).
        out2 = omnichannel_add_tag(db, DEFAULT_TENANT_ID, {"contactId": cid, "tagId": tag_id}, {})
        assert out2 == {"tags": [tag_id], "changed": False}
    finally:
        db.close()


def test_remove_tag_absent_is_no_op(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        tag_id = _add_tag(db, ws.id)
        db.commit()
        out = omnichannel_remove_tag(db, DEFAULT_TENANT_ID, {"contactId": cid, "tagId": tag_id}, {})
        assert out == {"tags": [], "changed": False}
    finally:
        db.close()


def test_add_tag_foreign_workspace_fails_and_writes_nothing(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import ContactTag, Workspace

        other_ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Other WS")
        db.add(other_ws)
        db.flush()
        foreign_tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=other_ws.id, name="Foreign")
        db.add(foreign_tag)
        db.commit()

        with pytest.raises(OmniActionError):
            omnichannel_add_tag(db, DEFAULT_TENANT_ID, {"contactId": cid, "tagId": foreign_tag.id}, {})

        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.custom_fields_json in (None, {})
    finally:
        db.close()


# ── AC-WFP-26: update_field ──────────────────────────────────────────────────
def test_update_field_sets_typed_value(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        key = _add_field(db, ws.id, key="budget", ftype="number")
        db.commit()

        out = omnichannel_update_field(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "fieldKey": key, "value": "42"}, {}
        )
        assert out == {"fieldKey": "budget", "value": 42}
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.custom_fields_json["budget"] == 42
    finally:
        db.close()


def test_update_field_invalid_value_fails_and_writes_nothing(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        key = _add_field(db, ws.id, key="budget", ftype="number")
        db.commit()

        with pytest.raises(OmniActionError):
            omnichannel_update_field(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "fieldKey": key, "value": "not-a-number"}, {}
            )
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert not (contact.custom_fields_json or {}).get("budget")
    finally:
        db.close()


def test_update_field_clear(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        key = _add_field(db, ws.id, key="notes", ftype="text")
        db.commit()
        omnichannel_update_field(db, DEFAULT_TENANT_ID, {"contactId": cid, "fieldKey": key, "value": "hi"}, {})
        out = omnichannel_update_field(db, DEFAULT_TENANT_ID, {"contactId": cid, "fieldKey": key, "clear": True}, {})
        assert out == {"fieldKey": "notes", "value": None}
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert "notes" not in (contact.custom_fields_json or {})
    finally:
        db.close()


# ── AC-WFP-27: update_lifecycle ──────────────────────────────────────────────
def test_update_lifecycle_moves_stage(session_factory):
    from modules.omnichannel.services import lifecycle_service

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        ws_id = contact.workspace_id
        contact.lifecycle_status_id = lifecycle_service.initial_status_id(db, DEFAULT_TENANT_ID, ws_id)
        db.commit()

        stages = lifecycle_service.stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)
        target = next(s for s in stages if s.id != contact.lifecycle_status_id)

        out = omnichannel_update_lifecycle(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "toStageId": target.id}, {}
        )
        assert out["toStageId"] == target.id
        assert out["stageLabel"] == target.label
        db.refresh(contact)
        assert contact.lifecycle_status_id == target.id
    finally:
        db.close()


def test_update_lifecycle_no_edge_fails(session_factory):
    from modules.omnichannel.services import lifecycle_service

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.id == cid).first()
        ws_id = contact.workspace_id
        stages = lifecycle_service.stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)
        terminal = next(s for s in stages if s.is_terminal)
        contact.lifecycle_status_id = terminal.id  # a terminal stage has no outgoing edge
        db.commit()

        other = next(s for s in stages if s.id != terminal.id)
        with pytest.raises(OmniActionError):
            omnichannel_update_lifecycle(db, DEFAULT_TENANT_ID, {"contactId": cid, "toStageId": other.id}, {})
    finally:
        db.close()


def test_update_lifecycle_foreign_stage_fails(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        with pytest.raises(OmniActionError):
            omnichannel_update_lifecycle(db, DEFAULT_TENANT_ID, {"contactId": cid, "toStageId": "nope"}, {})
    finally:
        db.close()


# ── AC-WFP-28: open_conversation ─────────────────────────────────────────────
def test_open_conversation_reopens_closed_thread(session_factory):
    cid = _seed_thread(session_factory, status_key="CLOSED", messages=[])
    db = session_factory()
    try:
        out = omnichannel_open_conversation(db, DEFAULT_TENANT_ID, {"contactId": cid}, {})
        assert out == {"status": "OPEN", "changed": True}
    finally:
        db.close()


def test_open_conversation_already_open_is_no_op(session_factory):
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[])
    db = session_factory()
    try:
        out = omnichannel_open_conversation(db, DEFAULT_TENANT_ID, {"contactId": cid}, {})
        assert out == {"status": "OPEN", "changed": False}
    finally:
        db.close()


# ── AC-WFP-29: close_conversation ────────────────────────────────────────────
def test_close_conversation_with_reason(session_factory):
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        reason_id = _add_close_reason(db, ws_id)
        db.commit()

        out = omnichannel_close_conversation(
            db, DEFAULT_TENANT_ID, {"contactId": cid, "closeReasonId": reason_id, "note": "done"}, {}
        )
        assert out == {"status": "CLOSED", "closeReasonId": reason_id}
    finally:
        db.close()


def test_close_conversation_already_closed_fails(session_factory):
    cid = _seed_thread(session_factory, status_key="CLOSED", messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        reason_id = _add_close_reason(db, ws_id)
        db.commit()
        with pytest.raises(OmniActionError, match="already closed"):
            omnichannel_close_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "closeReasonId": reason_id}, {}
            )
    finally:
        db.close()


def test_close_conversation_inactive_reason_fails(session_factory):
    cid = _seed_thread(session_factory, status_key="OPEN", messages=[])
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        reason_id = _add_close_reason(db, ws_id, is_active=False)
        db.commit()
        with pytest.raises(OmniActionError):
            omnichannel_close_conversation(
                db, DEFAULT_TENANT_ID, {"contactId": cid, "closeReasonId": reason_id}, {}
            )
    finally:
        db.close()


# ── AC-WFP-30: add_comment ────────────────────────────────────────────────────
def test_add_comment_writes_internal_note(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        out = omnichannel_add_comment(db, DEFAULT_TENANT_ID, {"contactId": cid, "body": "internal note"}, {})
        assert out["messageId"]
        from modules.omnichannel.models import ConversationMessage

        row = db.query(ConversationMessage).filter(ConversationMessage.id == out["messageId"]).first()
        assert row.sender_type == "SYSTEM"
        assert row.body == "internal note"
    finally:
        db.close()


def test_add_comment_empty_after_merge_fails(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        with pytest.raises(OmniActionError):
            omnichannel_add_comment(db, DEFAULT_TENANT_ID, {"contactId": cid, "body": "   "}, {})
    finally:
        db.close()


# ── AC-WFP-31/32/35: send_message template mode ─────────────────────────────
def test_send_message_template_mode_success(session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    tpl_id = _seed_template(session_factory)
    db = session_factory()
    try:
        out = omnichannel_send_message(
            db,
            DEFAULT_TENANT_ID,
            {
                "contactId": cid,
                "mode": "template",
                "templateId": tpl_id,
                "templateVariables": [{"key": "1", "value": "Sarah"}, {"key": "2", "value": "shipped"}],
            },
            {},
        )
        assert out["messageId"]
        from modules.omnichannel.models import ConversationMessage

        row = db.query(ConversationMessage).filter(ConversationMessage.id == out["messageId"]).first()
        assert row.message_type == "TEMPLATE"
    finally:
        db.close()


def test_send_message_template_not_approved_fails(session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    tpl_id = _seed_template(session_factory, status="PENDING")
    db = session_factory()
    try:
        with pytest.raises(OmniActionError):
            omnichannel_send_message(
                db,
                DEFAULT_TENANT_ID,
                {"contactId": cid, "mode": "template", "templateId": tpl_id, "templateVariables": []},
                {},
            )
    finally:
        db.close()


def test_send_message_template_placeholder_mismatch_fails(session_factory):
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    tpl_id = _seed_template(session_factory)  # needs {{1}} and {{2}}
    db = session_factory()
    try:
        with pytest.raises(OmniActionError):
            omnichannel_send_message(
                db,
                DEFAULT_TENANT_ID,
                {
                    "contactId": cid,
                    "mode": "template",
                    "templateId": tpl_id,
                    "templateVariables": [{"key": "1", "value": "only one"}],
                },
                {},
            )
    finally:
        db.close()


def test_send_message_sandbox_only_flows_through_template_mode(session_factory):
    """AC-WFP-35: manual/test runs stay sandbox-only in template mode too."""
    cid = _seed_thread(session_factory, messages=[{"body": "hi"}])
    tpl_id = _seed_template(session_factory)
    db = session_factory()
    try:
        out = omnichannel_send_message(
            db,
            DEFAULT_TENANT_ID,
            {
                "contactId": cid,
                "mode": "template",
                "templateId": tpl_id,
                "templateVariables": [{"key": "1", "value": "A"}, {"key": "2", "value": "B"}],
            },
            {"_workflow.sandboxOnly": True},
        )
        from modules.omnichannel.models import ConversationMessage

        row = db.query(ConversationMessage).filter(ConversationMessage.id == out["messageId"]).first()
        assert (row.metadata_json or {}).get("workflowTest", {}).get("sandboxOnly") is True
    finally:
        db.close()


# ── AC-WFP-33/34: workflow.trigger ───────────────────────────────────────────
def _publish_manual(db, tenant_id=DEFAULT_TENANT_ID, *, name="Child") -> Workflow:
    doc = {
        "schemaVersion": 2,
        "nodes": [{"id": "trg", "kind": "trigger", "type": "manual", "config": {}}],
        "edges": [],
    }
    svc = WorkflowService(db)
    wf = svc.create(tenant_id, name=name, description="", draft=doc, actor_id=None)
    svc.set_active(wf.id, tenant_id, True)
    svc.publish(wf.id, tenant_id, actor_id=None)
    db.refresh(wf)
    return wf


def test_workflow_trigger_starts_child_run(session_factory):
    db = session_factory()
    try:
        child = _publish_manual(db)
        child_id = child.id
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        out = workflow_trigger(
            db,
            DEFAULT_TENANT_ID,
            {"workflowId": child_id, "payload": '{"hello":"world"}'},
            {"_workflow.runId": None, "_workflow.workflowId": "parent-wf"},
        )
        db.commit()
        assert out["workflowId"] == child_id
        run = db.query(WorkflowRun).filter(WorkflowRun.id == out["runId"]).first()
        assert run is not None
        assert run.status == RUN_SUCCESS
        assert run.trigger_payload_json["eventData"]["source"] == "workflow"
        assert run.trigger_payload_json["eventData"]["payload"] == {"hello": "world"}
    finally:
        db.close()


def test_workflow_trigger_unpublished_target_fails(session_factory):
    db = session_factory()
    try:
        doc = {
            "schemaVersion": 2,
            "nodes": [{"id": "trg", "kind": "trigger", "type": "manual", "config": {}}],
            "edges": [],
        }
        wf = WorkflowService(db).create(
            DEFAULT_TENANT_ID, name="Draft only", description="", draft=doc, actor_id=None
        )
        db.commit()
        with pytest.raises(CoreActionError):
            workflow_trigger(db, DEFAULT_TENANT_ID, {"workflowId": wf.id}, {})
    finally:
        db.close()


def test_workflow_trigger_foreign_tenant_target_fails(session_factory):
    db = session_factory()
    try:
        from app.services.tenant_service import TenantService

        other = TenantService(db).provision(
            name="Other Co", slug="wfp-other-tenant",
            admin_name="Admin", admin_email="admin@wfp-other.example",
            admin_password="Passw0rd!23",
        )
        child = _publish_manual(db, tenant_id=other.id, name="Other Child")
        child_id = child.id
        db.commit()
        with pytest.raises(CoreActionError):
            workflow_trigger(db, DEFAULT_TENANT_ID, {"workflowId": child_id}, {})
    finally:
        db.close()


def test_workflow_trigger_self_refused_at_publish(session_factory):
    db = session_factory()
    try:
        doc = {
            "schemaVersion": 2,
            "nodes": [
                {"id": "trg", "kind": "trigger", "type": "manual", "config": {}},
                {
                    "id": "wt_1",
                    "kind": "action",
                    "type": "workflow.trigger",
                    "config": {"workflowId": "__SELF__"},
                },
            ],
            "edges": [{"id": "e1", "source": "trg", "target": "wt_1"}],
        }
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name="Self Trigger", description="", draft=doc, actor_id=None)
        wf.draft_definition_json["nodes"][1]["config"]["workflowId"] = wf.id
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(wf, "draft_definition_json")
        db.commit()
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        with pytest.raises(WorkflowValidationError, match="A workflow cannot trigger itself"):
            svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    finally:
        db.close()


def test_workflow_trigger_depth_cap(session_factory):
    from app.models.workflow import MAX_RUN_DEPTH

    db = session_factory()
    try:
        child = _publish_manual(db)
        child_id = child.id
        run = WorkflowRun(
            tenant_id=DEFAULT_TENANT_ID,
            workflow_id=child_id,
            version_id=child.current_version_id,
            version_number=1,
            status=RUN_SUCCESS,
            definition_snapshot_json={},
            trigger_payload_json={},
            depth=MAX_RUN_DEPTH,
        )
        db.add(run)
        db.commit()
        with pytest.raises(CoreActionError, match="depth limit"):
            workflow_trigger(
                db,
                DEFAULT_TENANT_ID,
                {"workflowId": child_id},
                {"_workflow.runId": run.id, "_workflow.workflowId": "parent-wf"},
            )
    finally:
        db.close()


def test_workflow_trigger_rejects_non_contact_entity_target(session_factory):
    """AC-WFP-33 Pinned note: target must be entity-less or omnichannel_contact."""
    db = session_factory()
    try:
        doc = {
            "schemaVersion": 2,
            "nodes": [{"id": "trg", "kind": "trigger", "type": "entity.created", "config": {"entityType": "user"}}],
            "edges": [],
        }
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name="Entity Trigger", description="", draft=doc, actor_id=None)
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        db.commit()
        with pytest.raises(CoreActionError):
            workflow_trigger(db, DEFAULT_TENANT_ID, {"workflowId": wf.id}, {})
    finally:
        db.close()


# ── End-to-end: conversation_closed -> add_tag + update_field + send(template) ─
def test_end_to_end_closed_workflow_tags_fields_and_sends_template(session_factory):
    from modules.omnichannel.services.conversation_service import ConversationService

    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    tpl_id = _seed_template(session_factory)
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        tag_id = _add_tag(db, ws_id, name="closed-e2e")
        field_key = _add_field(db, ws_id, key="e2enotes", ftype="text")
        db.commit()
    finally:
        db.close()

    ai_id = "add_tag_1"
    field_id = "update_field_1"
    send_id = "send_1"
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "omnichannel.conversation_closed", "config": {}},
            {
                "id": ai_id,
                "kind": "action",
                "type": "omnichannel.add_tag",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "workspaceId": ws_id,
                    "tagId": tag_id,
                },
            },
            {
                "id": field_id,
                "kind": "action",
                "type": "omnichannel.update_field",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "workspaceId": ws_id,
                    "fieldKey": field_key,
                    "value": "handled",
                },
            },
            {
                "id": send_id,
                "kind": "action",
                "type": "omnichannel.send_message",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "mode": "template",
                    "templateId": tpl_id,
                    "templateVariables": [{"key": "1", "value": "Sarah"}, {"key": "2", "value": "closed"}],
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": ai_id},
            {"id": "e2", "source": ai_id, "target": field_id},
            {"id": "e3", "source": field_id, "target": send_id},
        ],
    }
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name="E2E closed", description="", draft=doc, actor_id=None)
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        wf_id = wf.id
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()

    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        assert runs[0].status == RUN_SUCCESS

        from modules.omnichannel.models import Contact, ConversationMessage

        contact = db.query(Contact).filter(Contact.id == cid).first()
        assert contact.custom_fields_json.get("e2enotes") == "handled"

        from modules.omnichannel.services.contact_tag_service import ContactTagService

        assert tag_id in ContactTagService(db).ids_for_contact(cid, DEFAULT_TENANT_ID)

        node_types = {n.node_type: n.status for n in runs[0].nodes}
        assert node_types["omnichannel.send_message"] == "success"
        sent = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.contact_id == cid, ConversationMessage.message_type == "TEMPLATE")
            .first()
        )
        assert sent is not None
    finally:
        db.close()


# ── AC-WFP-32 (plan 31 S3 review SF-5): an already-committed step is NOT
# rolled back by a later node's failure - each A5 step commits its own write
# immediately (module docstring D-A5-5), so a downstream failure only halts
# the REST of the run. ─────────────────────────────────────────────────────
def test_committed_step_survives_a_later_node_failure(session_factory):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.contact_tag_service import ContactTagService

    cid = _seed_thread(session_factory, status_key="OPEN", messages=[{"body": "hi"}])
    db = session_factory()
    try:
        ws_id = db.query(Contact).filter(Contact.id == cid).first().workspace_id
        tag_id = _add_tag(db, ws_id, name="wfp32-survives")
        db.commit()
    finally:
        db.close()

    tag_node_id = "tag_1"
    fail_node_id = "field_1"
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "omnichannel.conversation_closed", "config": {}},
            {
                "id": tag_node_id,
                "kind": "action",
                "type": "omnichannel.add_tag",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "workspaceId": ws_id,
                    "tagId": tag_id,
                },
            },
            {
                "id": fail_node_id,
                "kind": "action",
                "type": "omnichannel.update_field",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "workspaceId": ws_id,
                    # No such field in this workspace - guaranteed ActionError.
                    "fieldKey": "does-not-exist",
                    "value": "x",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": tag_node_id},
            {"id": "e2", "source": tag_node_id, "target": fail_node_id},
        ],
    }
    db = session_factory()
    try:
        svc = WorkflowService(db)
        wf = svc.create(DEFAULT_TENANT_ID, name="WFP-32 pin", description="", draft=doc, actor_id=None)
        svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
        svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
        wf_id = wf.id
        db.commit()
    finally:
        db.close()

    from modules.omnichannel.services.conversation_service import ConversationService

    db = session_factory()
    try:
        ConversationService(db).patch_thread(cid, DEFAULT_TENANT_ID, status="CLOSED")
    finally:
        db.close()

    db = session_factory()
    try:
        runs = _runs_for(db, wf_id)
        assert len(runs) == 1
        run = runs[0]
        # The run as a whole is FAILED (the downstream node's error halts it) ...
        assert run.status == RUN_FAILED
        node_types = {n.node_type: n.status for n in run.nodes}
        assert node_types["omnichannel.add_tag"] == "success"
        assert node_types["omnichannel.update_field"] == "failed"
        # ... but the already-committed tag write from node 1 SURVIVES - it is
        # never rolled back by node 2's later failure (AC-WFP-32).
        assert tag_id in ContactTagService(db).ids_for_contact(cid, DEFAULT_TENANT_ID)
    finally:
        db.close()


# ── AC-WFP-34 (plan 31 S3 review SF-5): every A5 executor fails closed when
# the omnichannel module is deactivated for the tenant - not just get_contact
# (already pinned in test_omnichannel_workflow_triggers.py). ────────────────
def test_every_a5_action_rejects_when_module_inactive(session_factory):
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.services.workflow_actions import (
        omnichannel_open_conversation,
        omnichannel_update_field,
        omnichannel_update_lifecycle,
    )

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
        empty_ctx: dict = {}
        config = {"contactId": cid}
        for fn in (
            omnichannel_send_message,
            omnichannel_assign_conversation,
            omnichannel_add_tag,
            omnichannel_remove_tag,
            omnichannel_update_field,
            omnichannel_update_lifecycle,
            omnichannel_open_conversation,
            omnichannel_close_conversation,
            omnichannel_add_comment,
        ):
            with pytest.raises(OmniActionError, match="not active"):
                fn(db, DEFAULT_TENANT_ID, config, empty_ctx)
    finally:
        db.close()


# ── Plan 31 review round 1 B-3 regression (round-2 residual R-1) ────────────
# `workflow.trigger` dispatches the CHILD run on the SAME session under eager
# execution. Before the fix, the child's `run_workflow` cleared the session's
# `workflow_origin` unconditionally on exit, so every event the PARENT emitted
# from a LATER node carried NO origin - an empty loop-guard chain and a reset
# depth. The parent then re-triggered itself off its own write.
def _publish_graph(db, doc, name):
    svc = WorkflowService(db)
    wf = svc.create(DEFAULT_TENANT_ID, name=name, description="", draft=doc, actor_id=None)
    svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
    svc.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    db.refresh(wf)
    return wf


def _parent_doc(trigger_type, trigger_config, child_id, tag_id, workspace_id):
    """[trigger] -> [workflow.trigger child] -> [omnichannel.add_tag]."""
    return {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": trigger_type, "config": trigger_config},
            {
                "id": "chain_1",
                "kind": "action",
                "type": "workflow.trigger",
                "config": {"workflowId": child_id, "contactId": "{{ trigger.contact.id }}"},
            },
            {
                "id": "tag_1",
                "kind": "action",
                "type": "omnichannel.add_tag",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "workspaceId": workspace_id,
                    "tagId": tag_id,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "chain_1"},
            {"id": "e2", "source": "chain_1", "target": "tag_1"},
        ],
    }


def test_workflow_trigger_child_run_preserves_the_parent_origin(session_factory):
    """A parent that chains a child and THEN writes must not re-trigger itself:
    the tag its own `add_tag` step adds emits `updated` carrying the PARENT's
    origin, so the loop guard skips it. Exactly one parent run, one child run."""
    from modules.omnichannel.models import Contact, ContactTag
    from modules.omnichannel.services.contact_profile_service import ContactProfileService

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        trigger_tag = _add_tag(db, ws.id, name="Trigger tag")
        follow_tag = _add_tag(db, ws.id, name="Follow-up")
        db.commit()
        child = _publish_manual(db, name="B3 child")
        # Parent fires on ANY tag being added (the same event class its own
        # add_tag step emits) - the shape that actually cascades without the fix.
        parent = _publish_graph(
            db,
            _parent_doc("omnichannel.contact_tag_added", {}, child.id, follow_tag, ws.id),
            "B3 parent",
        )
        parent_id, child_id = parent.id, child.id
    finally:
        db.close()

    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        ContactProfileService(db).patch(contact, tag_ids=[trigger_tag])
        db.commit()
    finally:
        db.close()

    db = session_factory()
    try:
        parent_runs = _runs_for(db, parent_id)
        assert len(parent_runs) == 1, [r.trigger_payload_json for r in parent_runs]
        assert parent_runs[0].status == RUN_SUCCESS
        assert len(_runs_for(db, child_id)) == 1
        tags = {t.name for t in db.query(ContactTag).all()}
        assert {"Trigger tag", "Follow-up"} <= tags
    finally:
        db.close()


def test_conversation_closed_parent_chains_a_child_then_tags_once(session_factory):
    """The plan-31 review's own reproduction shape: a `conversation_closed`
    parent whose graph is [workflow.trigger] -> [add_tag]. One parent run, one
    child run, and the parent's later write still carries its origin."""
    from modules.omnichannel.models import Contact

    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ws = _default_workspace(db)
        tag_id = _add_tag(db, ws.id, name="Closed follow-up")
        reason_id = _add_close_reason(db, ws.id, name="Resolved")
        db.commit()
        child = _publish_manual(db, name="Closed child")
        parent = _publish_graph(
            db,
            _parent_doc("omnichannel.conversation_closed", {}, child.id, tag_id, ws.id),
            "Closed parent",
        )
        parent_id, child_id = parent.id, child.id
    finally:
        db.close()

    db = session_factory()
    try:
        from modules.omnichannel.services.conversation_service import ConversationService

        ConversationService(db).close_thread(
            cid, DEFAULT_TENANT_ID, close_reason_id=reason_id, note=None, actor=None
        )
    finally:
        db.close()

    db = session_factory()
    try:
        parent_runs = _runs_for(db, parent_id)
        assert len(parent_runs) == 1
        assert parent_runs[0].status == RUN_SUCCESS
        assert len(_runs_for(db, child_id)) == 1
        contact = db.query(Contact).filter(Contact.id == cid).first()
        from modules.omnichannel.services.contact_tag_service import ContactTagService

        assert ContactTagService(db).ids_for_contact(contact.id, DEFAULT_TENANT_ID) == [tag_id]
    finally:
        db.close()
