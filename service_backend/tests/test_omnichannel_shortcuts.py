"""Plan sprint-4/27 (A3) S3 - the omnichannel module's shortcut routes
(`GET/POST /omnichannel/contacts/{id}/shortcuts...`). Covers AC-IVE-36/37/39/
40/42 at the module/router level; the generic core trigger + service behavior
(AC-IVE-35/38) is covered in `tests/test_workflow_shortcuts.py`.

Reuses the existing conversation-test seams (`_seed_thread`, `_auth`,
`_other_tenant_auth`) rather than duplicating fixture setup.
"""
from fastapi import HTTPException
import pytest
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.models.workflow import WorkflowVersion
from app.security import hash_password
from app.services.workflow_service import WorkflowService
from modules.omnichannel.embed_auth import ConversationPrincipal
from tests.test_omnichannel_contact_data_model import _auth, _other_tenant_auth
from tests.test_omnichannel_conversations import _seed_thread

ENTITY_TYPE = "omnichannel_contact"


def _actor(db, email="demo@example.com") -> User:
    return db.query(User).filter(User.email == email).one()


def _doc(entity_type=ENTITY_TYPE, *, field="countryCode", value="my"):
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": "entity.shortcut", "config": {"entityType": entity_type}},
            {
                "id": "upd_1",
                "kind": "action",
                "type": "entity.update",
                "config": {
                    "entityType": entity_type,
                    "recordId": "{{ trigger.record.id }}",
                    "assignments": [{"field": field, "value": value}],
                },
            },
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "upd_1", "sourcePort": "out"}],
    }


def _publish_shortcut_workflow(
    db, *, name=None, entity_type=ENTITY_TYPE, is_active=True, tenant_id=DEFAULT_TENANT_ID, draft=None,
):
    admin = _actor(db)
    service = WorkflowService(db)
    wf = service.create(
        tenant_id, name=name or "Shortcut WF", description="",
        draft=draft or _doc(entity_type), actor_id=admin.id, actor=admin,
    )
    if is_active:
        service.set_active(wf.id, tenant_id, True)
    service.publish(wf.id, tenant_id, actor_id=admin.id, actor=admin)
    db.refresh(wf)
    return wf


# ── AC-IVE-36: list published entity.shortcut/omnichannel_contact workflows ─
def test_list_shortcuts_returns_published_workflow(client, session_factory):
    cid = _seed_thread(session_factory, name="List Shortcut Target")
    db = session_factory()
    wf = _publish_shortcut_workflow(db, name="Send NPS survey")
    wf_id = wf.id
    # A draft-only workflow (never published) must never appear.
    admin = _actor(db)
    WorkflowService(db).create(
        DEFAULT_TENANT_ID, name="Draft only", description="", draft=_doc(), actor_id=admin.id, actor=admin
    )
    db.close()

    h = _auth(client)
    res = client.get(f"/omnichannel/contacts/{cid}/shortcuts", headers=h)
    assert res.status_code == 200, res.text
    assert res.json() == [{"workflowId": wf_id, "name": "Send NPS survey"}]


def test_list_shortcuts_unknown_contact_is_404(client, session_factory):
    h = _auth(client)
    assert client.get("/omnichannel/contacts/nope/shortcuts", headers=h).status_code == 404


# ── AC-IVE-37/38: run against the PUBLISHED version, validated + fanned out ─
def test_run_shortcut_happy_path_validates_and_publishes_webhook(client, session_factory):
    """Mirrors `test_workflow_entity_update_on_contact_validates_and_fans_out_
    webhook` (B11) but fired through the SHORTCUT route instead of a manual
    run - proves the shortcut path inherits the SAME `apply_update`
    validation/normalization + realtime/webhook fan-out, not a re-implementation."""
    from modules.omnichannel.models import Contact, WebhookDelivery

    from tests.test_omnichannel_api_gateway import _seeded

    hdr, cid = _seeded(client, session_factory, phone="+60177000012")
    reg = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "w", "url": "https://hooks.example.com/w", "events": ["contact.updated"]},
        headers=hdr,
    )
    assert reg.status_code == 201, reg.text

    db = session_factory()
    wf = _publish_shortcut_workflow(db, name="Normalize country")
    wf_id = wf.id
    db.close()

    h = _auth(client)
    res = client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["runId"]

    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    assert contact.country_code == "MY"  # normalized, not the raw rendered "my"
    delivery = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.event_type == "contact.updated")
        .order_by(WebhookDelivery.created_at.desc())
        .first()
    )
    assert delivery is not None
    db.close()


def test_run_shortcut_unknown_contact_is_404(client, session_factory):
    db = session_factory()
    wf = _publish_shortcut_workflow(db)
    wf_id = wf.id
    db.close()
    h = _auth(client)
    assert client.post(f"/omnichannel/contacts/nope/shortcuts/{wf_id}", headers=h).status_code == 404


def test_run_shortcut_rejects_workflow_of_another_entity(client, session_factory):
    """A workflow whose `entity.shortcut` binds a DIFFERENT entity (e.g. the
    core `user` entity) is a uniform 404, never leaked as a run (AC-IVE-38)."""
    cid = _seed_thread(session_factory, name="Wrong entity target")
    db = session_factory()
    admin = _actor(db)
    service = WorkflowService(db)
    other_doc = {
        "schemaVersion": 1,
        "nodes": [{"id": "trg_1", "kind": "trigger", "type": "entity.shortcut", "config": {"entityType": "user"}}],
        "edges": [],
    }
    wf = service.create(DEFAULT_TENANT_ID, name="For users only", description="", draft=other_doc, actor_id=admin.id, actor=admin)
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    wf_id = wf.id
    db.close()

    h = _auth(client)
    res = client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h)
    assert res.status_code == 404


def test_run_shortcut_rejects_unpublished(client, session_factory):
    cid = _seed_thread(session_factory, name="Unpublished target")
    db = session_factory()
    admin = _actor(db)
    wf = WorkflowService(db).create(
        DEFAULT_TENANT_ID, name="Draft only", description="", draft=_doc(), actor_id=admin.id, actor=admin
    )
    wf_id = wf.id
    db.close()

    h = _auth(client)
    assert client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h).status_code == 404


def test_run_shortcut_rejects_code_node_without_authorization(client, session_factory):
    """A shortcut whose published version carries a Code node with NO
    `code_authorized_by` stamp is a 409, no run created (AC-IVE-38, D-A3-10 -
    the fail-closed gate is inherited from `create_run_for_event`, not
    re-implemented in this module)."""
    from app.workflow_engine.code_runner import use_code_runner_client
    from tests.test_code_workflow_action import FakeRunner

    cid = _seed_thread(session_factory, name="Code shortcut target")
    db = session_factory()
    admin = _actor(db)
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg_1", "kind": "trigger", "type": "entity.shortcut", "config": {"entityType": ENTITY_TYPE}},
            {"id": "code_1", "kind": "action", "type": "code.run", "config": {
                "language": "python", "source": "result = {}", "inputs": [],
                "outputs": [{"key": "ok", "type": "string", "required": True}],
            }},
        ],
        "edges": [{"id": "e1", "source": "trg_1", "target": "code_1"}],
    }
    service = WorkflowService(db)
    wf = service.create(DEFAULT_TENANT_ID, name="Shortcut with code", description="", draft=doc, actor_id=admin.id, actor=admin)
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    with use_code_runner_client(FakeRunner(healthy=True)):
        service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=admin.id, actor=admin)
    version = db.query(WorkflowVersion).filter(WorkflowVersion.id == wf.current_version_id).one()
    version.code_authorized_by = None
    db.commit()
    wf_id = wf.id
    db.close()

    h = _auth(client)
    res = client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h)
    assert res.status_code == 409


# ── AC-IVE-42: tenant isolation ──────────────────────────────────────────────
def test_shortcut_routes_tenant_isolation(client, session_factory):
    cid = _seed_thread(session_factory, name="Isolated target")
    db = session_factory()
    wf = _publish_shortcut_workflow(db, name="Mine only")
    wf_id = wf.id
    db.close()

    h2 = _other_tenant_auth(client, session_factory, slug="other-ive-shortcut")
    assert client.get(f"/omnichannel/contacts/{cid}/shortcuts", headers=h2).status_code == 404
    assert client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h2).status_code == 404


# ── AC-IVE-42: permission gate (403 per write key) ──────────────────────────
def test_shortcut_routes_require_conversations_shortcut_permission(client, session_factory):
    cid = _seed_thread(session_factory, name="No perm target")
    db = session_factory()
    wf = _publish_shortcut_workflow(db, name="Gated")
    wf_id = wf.id
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="noshortcut@example.com",
            password=hash_password("noperm1234"),
            name="No Shortcut Perm",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
    )
    db.commit()
    db.close()

    h = _auth(client, email="noshortcut@example.com", password="noperm1234")
    assert client.get(f"/omnichannel/contacts/{cid}/shortcuts", headers=h).status_code == 403
    assert client.post(f"/omnichannel/contacts/{cid}/shortcuts/{wf_id}", headers=h).status_code == 403


# ── AC-IVE-40: no embed cap ever grants the shortcut routes ─────────────────
def test_require_native_refuses_any_embed_principal_regardless_of_caps():
    embed = ConversationPrincipal(
        tenant_id=DEFAULT_TENANT_ID, is_embed=True, caps=["reply", "assign", "close", "note", "send_template"],
    )
    with pytest.raises(HTTPException) as exc:
        embed.require_native("conversations.shortcut")
    assert exc.value.status_code == 403

    native_ok = ConversationPrincipal(
        tenant_id=DEFAULT_TENANT_ID, is_embed=False, permission_keys={"conversations.shortcut"},
    )
    native_ok.require_native("conversations.shortcut")  # does not raise

    native_missing = ConversationPrincipal(tenant_id=DEFAULT_TENANT_ID, is_embed=False, permission_keys=set())
    with pytest.raises(HTTPException) as exc2:
        native_missing.require_native("conversations.shortcut")
    assert exc2.value.status_code == 403
