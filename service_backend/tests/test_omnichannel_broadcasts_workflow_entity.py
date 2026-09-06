"""Omnichannel Broadcasts - plan 29 S3 (BE events + polish). Covers the three
S3 rows not already exercised by S2a/S2b: AC-BRD-44 (workflow entity
registration - facts resolve, `entity.update` writable is EMPTY), AC-BRD-46
(no public-gateway surface for broadcasts - review round 1, S4) and
AC-BRD-48 (`uninstall_tenant` wipes this tenant's broadcasts + recipients,
another tenant's rows untouched). AC-BRD-43/45/47/49/50 already have
dedicated coverage in `test_omnichannel_broadcasts.py` /
`test_omnichannel_broadcasts_send.py` - not duplicated here."""
import pathlib

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


def test_status_key_fact_resolution_is_tenant_scoped(client, session_factory) -> None:
    """Review round 1, S6 (the polymorphic stored-id rule) - `_status_key`
    used to resolve `Status.id == obj.status_id` with NO tenant filter, even
    though `broadcast_send_service._current_status_key` already scopes the
    SAME lookup correctly. Prove the fix fails closed rather than leaking a
    foreign tenant's status label if `status_id` is ever corrupted/planted
    to point at another tenant's row (defense-in-depth, same class as the
    status-engine notification / omnichannel gateway leaks this rule guards
    against elsewhere in the codebase)."""
    from app.models import Tenant
    from modules.omnichannel.models import Status

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(
        _broadcasts_base(ws), headers=h,
        json=_create_payload(channel_id, template_id, audience={
            "kind": "contacts", "contactIds": [contact_id],
        }),
    ).json()

    _other_tenant_auth(client, session_factory)  # provisions + installs omnichannel for a second tenant

    db = session_factory()
    other_tenant = db.query(Tenant).filter(Tenant.slug == "other-ctm").first()
    foreign_status_id = (
        db.query(Status.id)
        .filter(Status.tenant_id == other_tenant.id, Status.scope == "BROADCAST", Status.key == "DRAFT")
        .scalar()
    )
    assert foreign_status_id is not None
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    row.status_id = foreign_status_id  # simulate a corrupted/planted stored id
    db.commit()

    facts = record_facts(db, "omnichannel_broadcast", row)
    db.close()
    assert facts["record.status"] is None  # fails closed - never resolves the foreign tenant's key


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


# ── AC-BRD-46: no public-gateway surface for broadcasts (review round 1, S4) ─
def _module_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "modules" / "omnichannel"


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def test_gateway_router_carries_no_broadcast_surface() -> None:
    """`routers/api_v1.py` is the public `/api/v1/omnichannel/*` gateway
    (workspace-API-key auth) - AC-BRD-46 requires it stay UNCHANGED by this
    whole slice (broadcasts have no v1 gateway surface). A textual "no
    mention of broadcast" check is the durable regression guard: it fails
    the instant a future change wires a `/broadcasts` route, a `Rio*`
    broadcast field, or a mention in the consumer guide onto the gateway -
    forcing the review-gate rule this module's own reference doc states
    (`CLAUDE.md`: a `Rio*`/`api_v1.py` diff without a guide diff is an
    automatic review question)."""
    text = (_module_root() / "routers" / "api_v1.py").read_text().lower()
    assert "broadcast" not in text


def test_gateway_rio_schemas_carry_no_broadcast_field() -> None:
    """Same guard over the `Rio*` respond.io-parity schema family - a
    broadcast concept must not leak into ANY `Rio*` class (contact/message/
    thread/template/webhook shapes)."""
    text = (_module_root() / "schemas.py").read_text()
    lines = text.splitlines()
    in_rio_class = False
    for line in lines:
        if line.startswith("class Rio"):
            in_rio_class = True
        elif line and not line[0].isspace() and not line.startswith("class Rio"):
            in_rio_class = False
        if in_rio_class:
            assert "broadcast" not in line.lower(), f"Rio* schema mentions broadcast: {line!r}"


def test_consumer_integration_guide_carries_no_broadcast_mention() -> None:
    """The published consumer contract (`documentation/omnichannel/
    consumer-integration-guide.md`) must not mention broadcasts - there is
    nothing there for an external API-key integrator to read about, because
    v1 exposes no such endpoint."""
    guide = _repo_root() / "documentation" / "omnichannel" / "consumer-integration-guide.md"
    assert guide.exists()
    assert "broadcast" not in guide.read_text().lower()
