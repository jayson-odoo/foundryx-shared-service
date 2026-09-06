"""Omnichannel Broadcasts - plan 29 S3 (BE events + polish). Covers the two
S3 rows not already exercised by S2a/S2b: AC-BRD-44 (workflow entity
registration - facts resolve, `entity.update` writable is EMPTY) and
AC-BRD-48 (`uninstall_tenant` wipes this tenant's broadcasts + recipients,
another tenant's rows untouched). AC-BRD-43/45/47/49/50 already have
dedicated coverage in `test_omnichannel_broadcasts.py` /
`test_omnichannel_broadcasts_send.py` - not duplicated here."""
from app.models import DEFAULT_TENANT_ID
from app.workflow_engine.actions.entity_actions import ActionError, entity_update
from app.workflow_engine.entities import get_workflow_entity, record_facts
from modules.omnichannel.models import Broadcast, BroadcastRecipient
from tests.test_omnichannel_contacts_module import _other_tenant_auth, _workspace_id
from tests.test_omnichannel_broadcasts import _add_identity, _broadcasts_base, _create_payload, _fixture


# ── AC-BRD-44: registration + facts resolve + writable empty ───────────────
def test_workflow_entity_registered() -> None:
    entity = get_workflow_entity("omnichannel_broadcast")
    assert entity is not None
    assert entity.label == "Broadcast"
    assert entity.model is Broadcast
    assert entity.writable == frozenset()
    assert entity.has_status is False
    assert entity.module == "omnichannel"


def test_record_facts_resolve_for_a_real_broadcast(client, session_factory) -> None:
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws), headers=h,
        json=_create_payload(channel_id, template_id, name="Fact Check", audience={
            "kind": "contacts", "contactIds": [contact_id],
        }),
    ).json()

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    facts = record_facts(db, "omnichannel_broadcast", row)
    db.close()

    assert facts["record.name"] == "Fact Check"
    assert facts["record.status"] == "DRAFT"
    assert facts["record.channelId"] == channel_id
    assert facts["record.templateId"] == template_id
    assert facts["record.totalCount"] == 0
    assert facts["record.sentCount"] == 0
    assert facts["record.deliveredCount"] == 0
    assert facts["record.readCount"] == 0
    assert facts["record.failedCount"] == 0
    assert facts["record.skippedCount"] == 0
    assert facts["record.scheduledAt"] is None


def test_record_status_fact_tracks_a_terminal_state(client, session_factory) -> None:
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws), headers=h,
        json=_create_payload(channel_id, template_id, audience={
            "kind": "contacts", "contactIds": [contact_id],
        }),
    ).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    facts = record_facts(db, "omnichannel_broadcast", row)
    db.close()
    assert facts["record.status"] == "SENT"
    assert facts["record.sentCount"] == 1


# ── AC-BRD-44: `entity.update` is unreachable - writable is EMPTY ──────────
def test_entity_update_rejected_broadcast_is_read_only(client, session_factory) -> None:
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws), headers=h,
        json=_create_payload(channel_id, template_id, audience={
            "kind": "contacts", "contactIds": [contact_id],
        }),
    ).json()

    db = session_factory()
    config = {
        "entityType": "omnichannel_broadcast",
        "recordId": created["id"],
        "assignments": [{"field": "name", "value": "Hijacked"}],
    }
    try:
        entity_update(db, DEFAULT_TENANT_ID, config, {})
        raised = False
    except ActionError:
        raised = True
    db.close()
    assert raised, "entity.update must reject a broadcast (empty writable whitelist)"


# ── AC-BRD-48: uninstall_tenant wipes broadcasts + recipients, tenant-scoped ─
def test_uninstall_tenant_deletes_broadcasts_and_recipients(client, session_factory) -> None:
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import Channel, Contact, Workspace, WhatsappTemplate
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws), headers=h,
        json=_create_payload(channel_id, template_id, audience={
            "kind": "contacts", "contactIds": [contact_id],
        }),
    ).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text

    db = session_factory()
    assert db.query(Broadcast).filter(Broadcast.tenant_id == DEFAULT_TENANT_ID).count() >= 1
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.tenant_id == DEFAULT_TENANT_ID).count() >= 1
    db.close()

    # A second tenant's own broadcast must survive tenant A's uninstall - the
    # generic `OmniBase` loop scopes by `tenant_id`, never by an unscoped
    # DELETE. Rows are inserted directly (the `_ensure_channel`/`_seed_contact`
    # helpers in `test_omnichannel_contacts_module` hardcode DEFAULT_TENANT_ID,
    # so they cannot seed a second tenant's fixtures).
    h2 = _other_tenant_auth(client, session_factory, slug="other-brd-uninstall")
    ws2_id = _workspace_id(client, h2)

    db = session_factory()
    ws2 = db.query(Workspace).filter(Workspace.id == ws2_id).first()
    tenant_b = ws2.tenant_id
    channel2 = Channel(
        tenant_id=tenant_b, workspace_id=ws2_id, channel_type="WHATSAPP", name="Other Bcast Channel",
        credentials_json=encrypt_credentials({"dev": True}), phone_number_id="pn-other-brd",
        display_phone_number="+60 11-222 2222", is_active=True,
        status_id=statuses.status_id_for(db, tenant_b, "CHANNEL", "ACTIVE"),
    )
    db.add(channel2)
    db.flush()
    contact2 = Contact(
        tenant_id=tenant_b, workspace_id=ws2_id, first_name="Bee", last_name="Two", priority="MEDIUM",
    )
    db.add(contact2)
    db.flush()
    contact2_id = contact2.id
    template2 = WhatsappTemplate(
        tenant_id=tenant_b, channel_id=channel2.id, name="tpl_other_tenant", language="en",
        category="UTILITY", status="APPROVED",
        components_json=[{"type": "BODY", "text": "Hi {{1}}, update: {{2}}."}],
    )
    db.add(template2)
    db.commit()
    channel2_id, template2_id = channel2.id, template2.id
    db.close()
    _add_identity(session_factory, contact2_id, channel2_id, tenant_id=tenant_b)

    created2 = client.post(
        _broadcasts_base(ws2_id), headers=h2,
        json=_create_payload(channel2_id, template2_id, audience={"kind": "contacts", "contactIds": [contact2_id]}),
    ).json()
    assert created2.get("id"), created2

    db = session_factory()
    AppStoreService(db).uninstall(DEFAULT_TENANT_ID, "omnichannel", "omnichannel")
    db.commit()
    assert db.query(Broadcast).filter(Broadcast.tenant_id == DEFAULT_TENANT_ID).count() == 0
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.tenant_id == DEFAULT_TENANT_ID).count() == 0
    assert db.query(Broadcast).filter(Broadcast.tenant_id == tenant_b).count() == 1
    db.close()
