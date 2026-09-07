"""Omnichannel Broadcasts - plan 29 S1 (model, builder CRUD, audience
resolution + snapshot, permissions). Covers AC-BRD-15..25 plus this slice's
share of AC-BRD-51 (the S1 rows of the full pytest matrix)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Broadcast,
    BroadcastRecipient,
    Channel,
    ContactChannelIdentity,
    ContactField,
    Status,
    WhatsappTemplate,
)
from modules.omnichannel.services import statuses
from modules.omnichannel.services.broadcast_audience import (
    preview_count,
    recompute_counts,
    snapshot_audience,
)
from modules.omnichannel.services.broadcast_bindings import (
    BindingValidationError,
    validate_bindings,
)
from modules.omnichannel.services.template_send import analyze_template
from modules.omnichannel.schemas import BroadcastBindings
from tests.test_omnichannel_contacts_module import (
    _auth,
    _base,
    _ensure_channel,
    _no_perm_auth,
    _other_tenant_auth,
    _seed_contact,
    _workspace_id,
)

ALEMBIC_REV = "0011_omni_broadcasts"


def _broadcasts_base(ws_id: str) -> str:
    return f"{_base(ws_id)}/broadcasts"


def _ensure_template(
    session_factory,
    channel_id,
    *,
    tenant_id=DEFAULT_TENANT_ID,
    name="tpl_test",
    tpl_status="APPROVED",
    components=None,
):
    db = session_factory()
    tpl = WhatsappTemplate(
        tenant_id=tenant_id,
        channel_id=channel_id,
        name=name,
        language="en",
        category="UTILITY",
        status=tpl_status,
        components_json=components
        or [{"type": "BODY", "text": "Hi {{1}}, update: {{2}}."}],
    )
    db.add(tpl)
    db.commit()
    tid = tpl.id
    db.close()
    return tid


def _add_identity(session_factory, contact_id, channel_id, tenant_id=DEFAULT_TENANT_ID):
    db = session_factory()
    db.add(
        ContactChannelIdentity(
            tenant_id=tenant_id,
            contact_id=contact_id,
            channel_id=channel_id,
            external_user_id=f"ext-{contact_id}",
        )
    )
    db.commit()
    db.close()


def _add_contact_field(session_factory, ws_id, key, *, tenant_id=DEFAULT_TENANT_ID):
    db = session_factory()
    db.add(
        ContactField(
            tenant_id=tenant_id, workspace_id=ws_id, key=key, label=key, type="text",
        )
    )
    db.commit()
    db.close()


def _valid_bindings():
    return {
        "header": [],
        "body": [
            {"source": "contactField", "field": "firstName", "fallback": "there"},
            {"source": "static", "text": "your booking"},
        ],
        "buttons": [],
    }


def _create_payload(channel_id, template_id, *, name="Test Broadcast", audience=None, bindings=None, scheduled_at=None):
    body = {
        "name": name,
        "channelId": channel_id,
        "audience": audience or {"kind": "contacts", "contactIds": []},
        "templateId": template_id,
        "bindings": bindings or _valid_bindings(),
    }
    if scheduled_at is not None:
        body["scheduledAt"] = scheduled_at
    return body


def _fixture(client, session_factory, *, template_components=None, tpl_status="APPROVED"):
    """Common rig: workspace + active channel + one contact w/ identity +
    one approved 2-var-body template. Returns (h, ws, channel_id, contact_id, template_id)."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    channel_id = _ensure_channel(session_factory, ws, name="Bcast Channel")
    contact_id = _seed_contact(session_factory, ws, first="Alex", last="Tan", phone="+60 12-000 1111")
    _add_identity(session_factory, contact_id, channel_id)
    template_id = _ensure_template(session_factory, channel_id, components=template_components, tpl_status=tpl_status)
    return h, ws, channel_id, contact_id, template_id


# ── AC-BRD-15/16: migration + status-scope seeding ──────────────────────────
def test_migration_revision_sanity():
    import importlib

    mod = importlib.import_module(f"modules.omnichannel.alembic.versions.{ALEMBIC_REV}")
    assert mod.revision == ALEMBIC_REV
    assert len(mod.revision) <= 32
    assert mod.down_revision == "0010_omni_contacts_module"


def test_broadcast_status_scope_seeded_on_install(session_factory):
    db = session_factory()
    rows = db.query(Status).filter(Status.tenant_id == DEFAULT_TENANT_ID, Status.scope == "BROADCAST").all()
    keys = {r.key for r in rows}
    assert keys == {"DRAFT", "SCHEDULED", "SENDING", "SENT", "CANCELLED", "FAILED"}
    db.close()


def test_ensure_statuses_idempotent_rerun(session_factory):
    db = session_factory()
    before = db.query(Status).filter(Status.tenant_id == DEFAULT_TENANT_ID, Status.scope == "BROADCAST").count()
    statuses.ensure_statuses(db, DEFAULT_TENANT_ID)
    db.commit()
    after = db.query(Status).filter(Status.tenant_id == DEFAULT_TENANT_ID, Status.scope == "BROADCAST").count()
    assert before == after == 6
    db.close()


def test_grant_sweep_on_update(client, session_factory):
    """AC-BRD-16/47: a tenant installed before this slice gets the BROADCAST
    scope + the three new permission keys without a manual step."""
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    state = AppStoreService(db)._installed_state(DEFAULT_TENANT_ID, "omnichannel")[1]
    state.installed_version = "0.4.0"
    db.commit()
    db.close()

    db2 = session_factory()
    module, new_state = AppStoreService(db2).update(DEFAULT_TENANT_ID, "omnichannel")
    # Plan 33 S1 bumped the manifest to 0.8.0 (plan 31 bumped it to 0.7.0
    # first) - this test pins "the CURRENT manifest version", not a fixed
    # string (updated the same way every prior version bump updated it
    # before, e.g. plan 27/28/29/31).
    assert module.version == "0.8.0"
    assert new_state.installed_version == "0.8.0"
    db2.close()

    h = _auth(client)
    perms = set(client.get("/auth/me", headers=h).json()["permissions"])
    assert {"broadcasts.read", "broadcasts.manage", "broadcasts.send"} <= perms


# ── AC-BRD-17/19: create happy path, audience stored as config only ─────────
def test_create_happy_path_draft_zero_counts_no_recipients(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})

    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "DRAFT"
    assert body["counts"] == {"total": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "skipped": 0}
    assert body["audience"] == {"kind": "contacts", "segmentId": None, "segmentName": None, "filter": None, "contactIds": [contact_id]}
    assert body["createdByUserId"]

    db = session_factory()
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == body["id"]).count() == 0
    db.close()


def test_create_with_segment_audience(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    seg = client.post(
        f"{_base(ws)}/contact-segments", headers=h,
        json={"name": "All Alex", "filter": {"kind": "group", "combinator": "and", "rules": [
            {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
        ]}},
    ).json()
    payload = _create_payload(channel_id, template_id, audience={"kind": "segment", "segmentId": seg["id"]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["audience"]["segmentName"] == "All Alex"


def test_create_with_filter_audience(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    filter_group = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
    ]}
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": filter_group})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["audience"]["filter"] == filter_group


# ── AC-BRD-18: create/update validation matrix (422 fieldErrors) ───────────
def test_create_name_required_and_length(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(channel_id, template_id, name="", audience={"kind": "contacts", "contactIds": [contact_id]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "name" in res.json()["detail"]["fieldErrors"]

    payload["name"] = "x" * 201
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "name" in res.json()["detail"]["fieldErrors"]


def test_create_channel_not_active_or_foreign(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload("nonexistent-channel", template_id, audience={"kind": "contacts", "contactIds": [contact_id]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "channelId" in res.json()["detail"]["fieldErrors"]


def test_create_audience_not_exactly_one_source(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(channel_id, template_id, audience={"kind": "contacts", "contactIds": []})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "audience" in res.json()["detail"]["fieldErrors"]


def test_create_segment_from_another_workspace_422(client, session_factory):
    from modules.omnichannel.models import Workspace

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    db = session_factory()
    other_ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Other WS", status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"))
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()

    seg = client.post(
        f"{_base(other_ws_id)}/contact-segments", headers=h, json={"name": "Foreign Seg"},
    ).json()

    payload = _create_payload(channel_id, template_id, audience={"kind": "segment", "segmentId": seg["id"]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "audience.segmentId" in res.json()["detail"]["fieldErrors"]


def test_create_invalid_filter_tree_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    bad_filter = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "notAField", "operator": "eq", "value": "x"}
    ]}
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": bad_filter})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "audience.filter" in res.json()["detail"]["fieldErrors"]


def test_create_contact_id_not_in_workspace_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(channel_id, template_id, audience={"kind": "contacts", "contactIds": ["nonexistent-contact"]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "audience.contactIds" in res.json()["detail"]["fieldErrors"]


def test_create_template_not_approved_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory, tpl_status="PENDING")
    payload = _create_payload(channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "templateId" in res.json()["detail"]["fieldErrors"]


def test_create_media_header_template_rejected(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(
        client, session_factory,
        template_components=[
            {"type": "HEADER", "format": "IMAGE"},
            {"type": "BODY", "text": "Hi {{1}}."},
        ],
    )
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [{"source": "static", "text": "there"}], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "templateId" in res.json()["detail"]["fieldErrors"]


def test_create_binding_count_mismatch_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [{"source": "static", "text": "only one"}], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body" in res.json()["detail"]["fieldErrors"]


def test_create_binding_unknown_field_and_missing_fallback_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [
            {"source": "contactField", "field": "notAField", "fallback": "x"},
            {"source": "static", "text": "ok"},
        ], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body.0.field" in res.json()["detail"]["fieldErrors"]

    payload["bindings"]["body"][0] = {"source": "contactField", "field": "firstName", "fallback": ""}
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body.0.fallback" in res.json()["detail"]["fieldErrors"]


def test_create_binding_unregistered_custom_field_422_then_registered_ok(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [
            {"source": "contactField", "field": "customFields.vip", "fallback": "no"},
            {"source": "static", "text": "ok"},
        ], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body.0.field" in res.json()["detail"]["fieldErrors"]

    _add_contact_field(session_factory, ws, "vip")
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201, res.text


def test_create_static_binding_rejects_token_syntax_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [
            {"source": "static", "text": "{{ contact.firstName }}"},
            {"source": "static", "text": "ok"},
        ], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body.0.text" in res.json()["detail"]["fieldErrors"]


def test_create_empty_static_binding_rejected_422(client, session_factory):
    """Review round 1, S3: an empty (or whitespace-only) static binding used
    to save cleanly, then resolve to a skipped recipient for EVERY
    recipient at send time (`SkipMissingVariable`) - reject it at save."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        bindings={"header": [], "body": [
            {"source": "static", "text": ""},
            {"source": "static", "text": "ok"},
        ], "buttons": []},
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "bindings.body.0.text" in res.json()["detail"]["fieldErrors"]

    payload["bindings"]["body"][0]["text"] = "   "
    res2 = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res2.status_code == 422
    assert "bindings.body.0.text" in res2.json()["detail"]["fieldErrors"]


def test_create_scheduled_at_in_past_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]}, scheduled_at=past,
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert "scheduledAt" in res.json()["detail"]["fieldErrors"]


def test_create_scheduled_at_future_accepted(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload = _create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]}, scheduled_at=future,
    )
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["scheduledAt"] is not None
    assert res.json()["status"] == "DRAFT"


# ── AC-BRD-20: list scoping, search, sort, filter ───────────────────────────
def test_list_search_and_filter_whitelist(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, name="Spring Promo", audience={"kind": "contacts", "contactIds": [contact_id]}))
    client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, name="Winter Sale", audience={"kind": "contacts", "contactIds": [contact_id]}))

    res = client.get(_broadcasts_base(ws), headers=h, params={"search": "Spring"})
    assert res.status_code == 200
    names = {b["name"] for b in res.json()["data"]}
    assert names == {"Spring Promo"}

    res = client.get(_broadcasts_base(ws), headers=h, params={"sortBy": "notAField"})
    assert res.status_code == 422


def test_list_status_segment(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]}))

    res = client.get(_broadcasts_base(ws), headers=h, params={"segment": "DRAFT"})
    assert res.status_code == 200
    assert res.json()["total"] == 1

    res = client.get(_broadcasts_base(ws), headers=h, params={"segment": "SENT"})
    assert res.status_code == 200
    assert res.json()["total"] == 0

    res = client.get(_broadcasts_base(ws), headers=h, params={"segment": "not-a-status"})
    assert res.status_code == 422


# ── AC-BRD-21: status-gated edits (409) ─────────────────────────────────────
def _force_status(session_factory, broadcast_id, key):
    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    row.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", key)
    db.commit()
    db.close()


def test_update_draft_editable_non_draft_409(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()

    res = client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h, json={"name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"

    _force_status(session_factory, created["id"], "SENT")
    res = client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h, json={"name": "Nope"})
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "broadcast_not_editable"


def test_update_scheduled_at_allowed_while_scheduled(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()
    _force_status(session_factory, created["id"], "SCHEDULED")

    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    res = client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h, json={"scheduledAt": future})
    assert res.status_code == 200

    res = client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h, json={"name": "Nope"})
    assert res.status_code == 409


def test_delete_draft_only(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()
    _force_status(session_factory, created["id"], "SCHEDULED")
    res = client.delete(f"{_broadcasts_base(ws)}/{created['id']}", headers=h)
    assert res.status_code == 409

    _force_status(session_factory, created["id"], "DRAFT")
    res = client.delete(f"{_broadcasts_base(ws)}/{created['id']}", headers=h)
    assert res.status_code == 204
    assert client.get(f"{_broadcasts_base(ws)}/{created['id']}", headers=h).status_code == 404


# ── AC-BRD-22: duplicate ─────────────────────────────────────────────────────
def test_duplicate_creates_distinct_draft_with_no_recipients(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, name="Original", audience={"kind": "contacts", "contactIds": [contact_id]})).json()
    _force_status(session_factory, created["id"], "SENT")

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/duplicate", headers=h)
    assert res.status_code == 201, res.text
    dup = res.json()
    assert dup["id"] != created["id"]
    assert dup["name"] != "Original"
    assert dup["status"] == "DRAFT"
    assert dup["counts"]["total"] == 0
    assert dup["scheduledAt"] is None
    assert dup["audience"] == created["audience"] or dup["audience"]["contactIds"] == created["audience"]["contactIds"]

    db = session_factory()
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == dup["id"]).count() == 0
    db.close()


# ── AC-BRD-23: audience preview ─────────────────────────────────────────────
def test_audience_preview_contacts_segment_filter(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)

    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "contacts", "contactIds": [contact_id]}})
    assert res.status_code == 200
    assert res.json()["count"] == 1

    filter_group = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
    ]}
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": filter_group}})
    assert res.status_code == 200
    assert res.json()["count"] == 1

    seg = client.post(f"{_base(ws)}/contact-segments", headers=h, json={"name": "AlexSeg", "filter": filter_group}).json()
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "segment", "segmentId": seg["id"]}})
    assert res.status_code == 200
    assert res.json()["count"] == 1


def test_audience_preview_unknown_segment_404_and_invalid_filter_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "segment", "segmentId": "nope"}})
    assert res.status_code == 404

    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": {
        "kind": "group", "combinator": "and", "rules": [{"kind": "condition", "field": "notAField", "operator": "eq", "value": "x"}]
    }}})
    assert res.status_code == 422


# ── D-4 (review round 1, AC-BRD-18/23): an empty/malformed filter must never
# silently resolve to "every contact in the workspace" ─────────────────────
def test_audience_preview_empty_filter_group_422_not_whole_workspace(client, session_factory):
    """A zero-rule top-level group used to return `200 {"count": <everyone>}`
    (`translate_filter` returns no clause for an empty group) - reject it
    with the same `{fieldErrors}` shape create/update use."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    empty = {"kind": "group", "combinator": "and", "rules": []}
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": empty}})
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"]


def test_audience_preview_nested_empty_group_422(client, session_factory):
    """A top-level group whose only rule is a further EMPTY sub-group has
    length 1 at the top (the frontend's shallow zod check would pass it) but
    contains no real condition anywhere - must still 422."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    nested_empty = {
        "kind": "group", "combinator": "and",
        "rules": [{"kind": "group", "combinator": "or", "rules": []}],
    }
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": nested_empty}})
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"]


def test_audience_preview_unknown_key_on_condition_422(client, session_factory):
    """`extra="forbid"` on `FilterCondition`/`FilterGroup` (app/schemas/
    filters.py) - a stray/unrecognised key is a 422, never silently dropped.
    Post-approval fix, O-5: `audience.filter` is a raw dict at the wire
    boundary specifically so this 422 lands as the SAME `{fieldErrors}`
    shape every other audience error uses, not pydantic's raw
    `{"detail": [{"type": "extra_forbidden", ...}]}` body (which used to
    leak here because `BroadcastAudienceIn.filter` was a typed nested
    model FastAPI validated before the router ever ran)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    malformed = {
        "kind": "group", "combinator": "and",
        "rules": [{"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex", "extraKey": "x"}],
    }
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": malformed}})
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"] == "Unknown filter field."


def test_audience_preview_valid_filter_still_resolves_count(client, session_factory):
    """Control: a real condition still works (proves the guard rejects only
    the vacuous shape, not a valid one)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    valid = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
    ]}
    res = client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h, json={"audience": {"kind": "filter", "filter": valid}})
    assert res.status_code == 200
    assert res.json()["count"] == 1


def test_create_empty_filter_group_422_not_whole_workspace(client, session_factory):
    """Same D-4 guard on the CREATE path - the previously-reproduced bug: an
    empty filter used to `201` and store `{"rules": []}`, resolving to every
    contact in the workspace at send time."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    empty = {"kind": "group", "combinator": "and", "rules": []}
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": empty})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"]


def test_create_nested_empty_filter_group_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    nested_empty = {
        "kind": "group", "combinator": "and",
        "rules": [{"kind": "group", "combinator": "or", "rules": []}],
    }
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": nested_empty})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"]


def test_create_filter_unknown_key_422(client, session_factory):
    """Post-approval fix, O-5: same normalized `{fieldErrors}` shape on the
    create path (see `test_audience_preview_unknown_key_on_condition_422`)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    malformed = {
        "kind": "group", "combinator": "and",
        "rules": [{"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex", "extraKey": "x"}],
    }
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": malformed})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"] == "Unknown filter field."


def test_update_filter_unknown_key_422(client, session_factory):
    """Same normalized shape on the UPDATE path (a draft broadcast that
    already exists, patched with a malformed inline filter)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    payload = _create_payload(
        channel_id, template_id,
        audience={"kind": "filter", "filter": {
            "kind": "group", "combinator": "and",
            "rules": [{"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}],
        }},
    )
    created = client.post(_broadcasts_base(ws), headers=h, json=payload).json()
    malformed = {
        "kind": "group", "combinator": "and",
        "rules": [{"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex", "extraKey": "x"}],
    }
    res = client.patch(
        f"{_broadcasts_base(ws)}/{created['id']}", headers=h,
        json={"audience": {"kind": "filter", "filter": malformed}},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["fieldErrors"]["audience.filter"] == "Unknown filter field."


def test_create_valid_filter_still_creates(client, session_factory):
    """Control: create still works with a real condition."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    valid = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
    ]}
    payload = _create_payload(channel_id, template_id, audience={"kind": "filter", "filter": valid})
    res = client.post(_broadcasts_base(ws), headers=h, json=payload)
    assert res.status_code == 201


# ── AC-BRD-24: tenant isolation, uniform 404 ────────────────────────────────
def test_tenant_isolation_uniform_404(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()

    h2 = _other_tenant_auth(client, session_factory, slug="other-brd")
    assert client.get(f"{_broadcasts_base(ws)}/{created['id']}", headers=h2).status_code == 404
    assert client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h2, json={"name": "x"}).status_code == 404
    assert client.delete(f"{_broadcasts_base(ws)}/{created['id']}", headers=h2).status_code == 404
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/duplicate", headers=h2).status_code == 404
    assert client.get(f"{_broadcasts_base(ws)}/{created['id']}/recipients", headers=h2).status_code == 404
    # the workspace itself is foreign to tenant B - every list/create route 404s too
    assert client.get(_broadcasts_base(ws), headers=h2).status_code == 404
    assert client.post(_broadcasts_base(ws), headers=h2, json=_create_payload(channel_id, template_id)).status_code == 404


# ── AC-BRD-25: permission gates per route ───────────────────────────────────
def test_permission_gates_per_route(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()

    h_none = _no_perm_auth(client, session_factory, email="brd-noperm@example.com")
    assert client.get(_broadcasts_base(ws), headers=h_none).status_code == 403
    assert client.get(f"{_broadcasts_base(ws)}/{created['id']}", headers=h_none).status_code == 403
    assert client.get(f"{_broadcasts_base(ws)}/{created['id']}/recipients", headers=h_none).status_code == 403
    assert client.post(f"{_broadcasts_base(ws)}/audience-preview", headers=h_none, json={"audience": {"kind": "contacts", "contactIds": []}}).status_code == 403
    assert client.post(_broadcasts_base(ws), headers=h_none, json=_create_payload(channel_id, template_id)).status_code == 403
    assert client.patch(f"{_broadcasts_base(ws)}/{created['id']}", headers=h_none, json={"name": "x"}).status_code == 403
    assert client.delete(f"{_broadcasts_base(ws)}/{created['id']}", headers=h_none).status_code == 403
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/duplicate", headers=h_none).status_code == 403


# ── Snapshot function (implemented + tested now; S2 wires it into the job) ──
def test_snapshot_queued_and_no_identity(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    no_identity_contact = _seed_contact(session_factory, ws, first="No", last="Identity", phone="+60 12-000 2222")

    payload = _create_payload(channel_id, template_id, audience={
        "kind": "contacts", "contactIds": [contact_id, no_identity_contact],
    })
    created = client.post(_broadcasts_base(ws), headers=h, json=payload).json()

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    result = snapshot_audience(db, row)
    db.commit()

    assert result["total"] == 2
    assert result["skippedByReason"]["no_identity"] == 1
    recips = {r.contact_id: (r.state, r.skip_reason) for r in db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id)}
    assert recips[contact_id] == ("queued", None)
    assert recips[no_identity_contact] == ("skipped", "no_identity")
    assert row.total_count == 2
    assert row.skipped_count == 1
    db.close()


def test_snapshot_channel_inactive_skips_everyone(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    channel.is_active = False
    db.commit()

    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    result = snapshot_audience(db, row)
    db.commit()

    assert result["skippedByReason"]["channel_inactive"] == 1
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id).first()
    assert recip.state == "skipped"
    assert recip.skip_reason == "channel_inactive"
    db.close()


def test_snapshot_idempotent_rerun_marks_duplicate_no_new_rows(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]})).json()

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    first = snapshot_audience(db, row)
    db.commit()
    assert first["total"] == 1
    assert first["skippedByReason"]["duplicate"] == 0

    second = snapshot_audience(db, row)
    db.commit()
    assert second["total"] == 1  # unchanged - no new rows
    assert second["skippedByReason"]["duplicate"] == 1

    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id).count() == 1
    db.close()


def test_snapshot_counts_match_live_aggregate_invariant(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    other = _seed_contact(session_factory, ws, first="Other", last="One", phone="+60 12-000 3333")
    _add_identity(session_factory, other, channel_id)

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id, other]})).json()

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, row)
    db.commit()

    # Simulate a state advance the way S2's chunk loop will (a live aggregate
    # recompute must still equal the denormalized counts afterwards).
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id).first()
    recip.state = "sent"
    db.commit()
    recompute_counts(db, row)
    db.commit()

    live_total = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id).count()
    live_sent = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id, BroadcastRecipient.state == "sent").count()
    assert row.total_count == live_total == 2
    assert row.sent_count == live_sent == 1
    db.close()


def test_snapshot_join_after_snapshot_not_sent_to(client, session_factory):
    """AC-BRD-27: the audience is resolved ONCE at snapshot time - a contact
    added to the workspace (matching the SAME filter) afterwards must not
    appear among this broadcast's recipients (S2's job orchestration never
    re-invokes the snapshot once recipients exist; this pins the query-level
    guarantee this slice ships)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    filter_group = {"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "firstName", "operator": "eq", "value": "Alex"}
    ]}
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "filter", "filter": filter_group})).json()

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, row)
    db.commit()
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == row.id).count() == 1
    db.close()

    late_contact = _seed_contact(session_factory, ws, first="Alex", last="Late", phone="+60 12-000 4444")
    _add_identity(session_factory, late_contact, channel_id)

    db2 = session_factory()
    assert db2.query(BroadcastRecipient).filter(
        BroadcastRecipient.broadcast_id == row.id, BroadcastRecipient.contact_id == late_contact
    ).first() is None
    db2.close()


def test_preview_count_matches_snapshot_total(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    count = preview_count(session_factory(), DEFAULT_TENANT_ID, ws, kind="contacts", contact_ids=[contact_id])
    assert count == 1


# ── bindings validation, direct unit coverage ───────────────────────────────
def test_validate_bindings_direct_count_and_whitelist(session_factory):
    db = session_factory()
    shape = analyze_template([{"type": "BODY", "text": "Hi {{1}}, {{2}}."}])
    bindings = BroadcastBindings.model_validate({"header": [], "body": [], "buttons": []})
    with pytest.raises(BindingValidationError) as exc:
        validate_bindings(db, DEFAULT_TENANT_ID, "irrelevant-ws", shape, bindings)
    assert "bindings.body" in exc.value.errors


# ── review round 1, B1: no DB-level FK from broadcasts/broadcast_recipients ──
def _enable_fk_enforcement(session_factory) -> None:
    """`channel_id`/`template_id`/`audience_segment_id`/`contact_id` on the
    broadcast tables are PLAIN INDEXED columns, not DB-level FKs (BL-030) -
    a channel/template/segment/contact hard-delete must never be blocked by a
    historical broadcast. SQLite doesn't enforce FKs by default, so without
    turning enforcement ON this whole test class would pass even if a real
    ``ForeignKey(...)`` were still declared on those columns (Postgres would
    then reject the very deletes this test proves succeed). The fixture's
    engine is a single StaticPool connection - the PRAGMA persists for every
    session opened against it for the rest of the test."""
    from sqlalchemy import text

    db = session_factory()
    engine = db.get_bind()
    db.close()
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()


def test_channel_template_segment_hard_delete_not_blocked_by_broadcast(client, session_factory):
    """B1: a broadcast referencing a channel/template/segment must never block
    those shipped hard-delete paths (`ChannelService.remove`,
    `TemplateManagementService.delete`, `ContactSegmentService.delete`) - even
    with real FK enforcement turned on."""
    from modules.omnichannel.models import ContactSegment
    from modules.omnichannel.services.channel_service import ChannelService
    from modules.omnichannel.services.contact_segment_service import ContactSegmentService
    from modules.omnichannel.services.template_management_service import TemplateManagementService

    _enable_fk_enforcement(session_factory)

    # A broadcast can only be CREATED against an APPROVED template
    # (`test_create_template_not_approved_422`) - downgrade to LOCAL_DRAFT
    # AFTER creation so the delete call skips the Meta adapter entirely.
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)

    db = session_factory()
    segment = ContactSegment(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws,
        name="Segment for delete test",
        filter_json={"kind": "group", "combinator": "and", "rules": []},
    )
    db.add(segment)
    db.commit()
    segment_id = segment.id
    db.close()

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "segment", "segmentId": segment_id},
    )).json()
    broadcast_id = created["id"]

    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert row.audience_segment_id == segment_id
    assert row.channel_id == channel_id
    assert row.template_id == template_id

    # Segment delete must succeed - the broadcast keeps its (now-dangling)
    # audience_segment_id, since there is no FK to enforce/cascade.
    ContactSegmentService(db).delete(segment_id, ws, DEFAULT_TENANT_ID)
    assert db.query(ContactSegment).filter(ContactSegment.id == segment_id).first() is None

    # Template delete must succeed (LOCAL_DRAFT never calls the Meta adapter).
    tpl = db.query(WhatsappTemplate).filter(WhatsappTemplate.id == template_id).first()
    tpl.status = "LOCAL_DRAFT"
    db.commit()
    TemplateManagementService(db).delete(channel_id, template_id, DEFAULT_TENANT_ID)
    assert db.query(WhatsappTemplate).filter(WhatsappTemplate.id == template_id).first() is None

    # Channel delete (hard delete) must succeed even with a broadcast still
    # pointing at its id.
    ChannelService(db).remove([channel_id], DEFAULT_TENANT_ID)
    assert db.query(Channel).filter(Channel.id == channel_id).first() is None

    # The broadcast row itself survives untouched - no cascade, no FK error.
    survivor = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert survivor is not None
    assert survivor.channel_id == channel_id
    assert survivor.template_id == template_id
    assert survivor.audience_segment_id == segment_id
    db.close()
