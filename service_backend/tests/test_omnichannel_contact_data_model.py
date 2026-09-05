"""Omnichannel contact data model - plan 25 S1 (contact fields registry, tags,
the ONE contact-profile write path). Covers AC-CDM-01..12, 22, 23, 28.

Reuses the existing conversation-test seams (`_seed_thread`, `_auth`) rather
than duplicating fixture setup.
"""
from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_conversations import _seed_thread


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _base(ws_id: str) -> str:
    return f"/omnichannel/workspaces/{ws_id}"


# ── AC-CDM-01/02: field create + validation matrix ───────────────────────────
def test_create_field_and_list_sorted(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    r1 = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "company", "label": "Company", "type": "text",
    })
    assert r1.status_code == 201
    r2 = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "dealValue", "label": "Deal Value", "type": "number",
    })
    assert r2.status_code == 201

    listed = client.get(f"{_base(ws)}/contact-fields", headers=h).json()
    assert [f["key"] for f in listed] == ["company", "dealValue"]
    assert listed[0]["sortOrder"] == 0 and listed[1]["sortOrder"] == 1
    assert listed[0]["valuesCount"] == 0


def test_create_field_validation_matrix(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    base = f"{_base(ws)}/contact-fields"

    # reserved key
    res = client.post(base, headers=h, json={"key": "email", "label": "E", "type": "text"})
    assert res.status_code == 422
    assert "key" in res.json()["detail"]["fieldErrors"]

    # bad regex (uppercase first char)
    res = client.post(base, headers=h, json={"key": "Company", "label": "C", "type": "text"})
    assert res.status_code == 422
    assert "key" in res.json()["detail"]["fieldErrors"]

    # bad type
    res = client.post(base, headers=h, json={"key": "widget", "label": "W", "type": "currency"})
    assert res.status_code == 422
    assert "type" in res.json()["detail"]["fieldErrors"]

    # list without options
    res = client.post(base, headers=h, json={"key": "source", "label": "Source", "type": "list"})
    assert res.status_code == 422
    assert "options" in res.json()["detail"]["fieldErrors"]

    # create then duplicate (case-insensitive)
    ok = client.post(base, headers=h, json={"key": "source", "label": "Source", "type": "list", "options": ["A"]})
    assert ok.status_code == 201
    dup = client.post(base, headers=h, json={"key": "Source", "label": "Source 2", "type": "text"})
    assert dup.status_code == 422
    assert "key" in dup.json()["detail"]["fieldErrors"]


def test_field_cap_100_per_workspace(client, session_factory):
    from modules.omnichannel.models import ContactField, Workspace

    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    for i in range(100):
        db.add(ContactField(
            tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, key=f"f{i}", label=f"F{i}",
            type="text", sort_order=i,
        ))
    db.commit()
    db.close()

    res = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "oneMore", "label": "One More", "type": "text",
    })
    assert res.status_code == 422


# ── AC-CDM-03: update - editable vs immutable ────────────────────────────────
def test_update_field_editable_and_immutable(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    created = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "source", "label": "Source", "type": "list", "options": ["A", "B"],
    }).json()
    fid = created["id"]

    ok = client.patch(f"{_base(ws)}/contact-fields/{fid}", headers=h, json={
        "label": "Lead Source", "description": "d", "options": ["A", "B", "C"],
        "visibility": "hidden", "sortOrder": 5,
    })
    assert ok.status_code == 200
    body = ok.json()
    assert body["label"] == "Lead Source"
    assert body["options"] == ["A", "B", "C"]
    assert body["visibility"] == "hidden"
    assert body["sortOrder"] == 5

    bad_key = client.patch(f"{_base(ws)}/contact-fields/{fid}", headers=h, json={"key": "renamed"})
    assert bad_key.status_code == 422
    assert "key" in bad_key.json()["detail"]["fieldErrors"]

    bad_type = client.patch(f"{_base(ws)}/contact-fields/{fid}", headers=h, json={"type": "text"})
    assert bad_type.status_code == 422
    assert "type" in bad_type.json()["detail"]["fieldErrors"]


# ── AC-CDM-04: delete strips values, other workspace untouched ───────────────
def test_delete_field_strips_values_scoped_to_workspace(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    other_ws = client.post("/omnichannel/workspaces", headers=h, json={"name": "Other WS"}).json()["id"]

    created = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "company", "label": "Company", "type": "text",
    }).json()
    fid = created["id"]

    cid_ws = _seed_thread(session_factory, name="In WS")
    cid_other = _seed_thread(session_factory, name="In Other")
    # Move the second contact into the other workspace + stamp both with values.
    db = session_factory()
    from modules.omnichannel.models import Contact

    db.query(Contact).filter(Contact.id == cid_ws).update({"custom_fields_json": {"company": "Acme"}})
    other = db.query(Contact).filter(Contact.id == cid_other).first()
    other.workspace_id = other_ws
    other.custom_fields_json = {"company": "Other Co"}
    db.commit()
    db.close()

    res = client.delete(f"{_base(ws)}/contact-fields/{fid}", headers=h)
    assert res.status_code == 204

    db = session_factory()
    in_ws = db.query(Contact).filter(Contact.id == cid_ws).first()
    in_other = db.query(Contact).filter(Contact.id == cid_other).first()
    assert "company" not in (in_ws.custom_fields_json or {})
    assert in_other.custom_fields_json == {"company": "Other Co"}  # untouched
    db.close()


def test_delete_field_strips_values_sqlite_fallback_path(session_factory):
    """Same as above but drives the service directly - the SQLite (pytest)
    dialect branch of `_strip_values`."""
    from modules.omnichannel.models import Contact, ContactField, Workspace
    from modules.omnichannel.services.contact_field_service import ContactFieldService

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    field = ContactField(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, key="k", label="K", type="text")
    db.add(field)
    contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="A",
                       custom_fields_json={"k": "v", "other": "keep"})
    db.add(contact)
    db.commit()

    assert db.get_bind().dialect.name == "sqlite"
    ContactFieldService(db).delete(field.id, ws.id, DEFAULT_TENANT_ID)
    db.refresh(contact)
    assert contact.custom_fields_json == {"other": "keep"}
    db.close()


# ── AC-CDM-06: contact PATCH customFields validation + partial merge ─────────
def test_patch_contact_custom_fields_full_type_matrix(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    base = f"{_base(ws)}/contact-fields"
    specs = [
        ("t", "text", None, "hello", "x" * 2001),
        ("n", "number", None, 42, "not-a-number"),
        ("chk", "checkbox", None, True, "not-a-bool"),
        ("em", "email", None, "a@b.com", "not-an-email"),
        ("u", "url", None, "https://example.com", "ftp nope"),
        ("d", "date", None, "2026-01-15", "15-01-2026"),
        ("tm", "time", None, "14:30", "2:30pm"),
    ]
    for key, ftype, _opts, good, bad in specs:
        res = client.post(base, headers=h, json={"key": key, "label": key, "type": ftype})
        assert res.status_code == 201, res.text
    client.post(base, headers=h, json={"key": "lst", "label": "L", "type": "list", "options": ["X", "Y"]})

    cid = _seed_thread(session_factory, name="Field Matrix")

    for key, _ftype, _opts, good, _bad in specs:
        res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {key: good}})
        assert res.status_code == 200, (key, res.text)
        assert res.json()["customFields"][key] == good

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {"lst": "X"}})
    assert res.status_code == 200
    assert res.json()["customFields"]["lst"] == "X"

    # bad values - nothing written, fieldErrors keyed customFields.<key>
    for key, _ftype, _opts, _good, bad in specs:
        before = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()["customFields"]
        res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {key: bad}})
        assert res.status_code == 422, (key, res.text)
        assert f"customFields.{key}" in res.json()["detail"]["fieldErrors"]
        after = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()["customFields"]
        assert after == before  # unchanged on failure

    # list value not in options
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {"lst": "Z"}})
    assert res.status_code == 422
    assert "customFields.lst" in res.json()["detail"]["fieldErrors"]

    # unknown key
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {"nope": "x"}})
    assert res.status_code == 422
    assert "customFields.nope" in res.json()["detail"]["fieldErrors"]

    # null clears one key; omitted keys stay unchanged (partial merge)
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": {"t": None}})
    assert res.status_code == 200
    body = res.json()["customFields"]
    assert "t" not in body
    assert body["n"] == 42  # untouched


# ── AC-CDM-07: language/countryCode validation ───────────────────────────────
def test_patch_contact_language_country_code(client, session_factory):
    h = _auth(client)
    cid = _seed_thread(session_factory, name="Lang Test")

    ok = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "language": "zh-Hans", "countryCode": "my",
    })
    assert ok.status_code == 200
    assert ok.json()["language"] == "zh-Hans"
    assert ok.json()["countryCode"] == "MY"  # upper-cased

    bad_country = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"countryCode": "MYS"})
    assert bad_country.status_code == 422
    assert "countryCode" in bad_country.json()["detail"]["fieldErrors"]

    bad_lang = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"language": "x" * 17})
    assert bad_lang.status_code == 422
    assert "language" in bad_lang.json()["detail"]["fieldErrors"]


# ── AC-CDM-08: cross-tenant 404 on every new route ───────────────────────────
def _other_tenant_auth(client, session_factory, slug="other-cdm"):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other CDM", slug=slug, admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()
    return _auth(client, email=f"admin-{slug}@example.com", password="Password123!", tenant_slug=slug)


def test_contact_field_routes_tenant_isolation(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    field = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "isoField", "label": "Iso", "type": "text",
    }).json()

    h2 = _other_tenant_auth(client, session_factory)
    assert client.get(f"{_base(ws)}/contact-fields", headers=h2).status_code == 404
    assert client.post(f"{_base(ws)}/contact-fields", headers=h2, json={
        "key": "x", "label": "X", "type": "text",
    }).status_code == 404
    assert client.patch(f"{_base(ws)}/contact-fields/{field['id']}", headers=h2, json={
        "label": "hacked",
    }).status_code == 404
    assert client.delete(f"{_base(ws)}/contact-fields/{field['id']}", headers=h2).status_code == 404


def test_contact_tag_routes_tenant_isolation(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    tag = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "IsoTag"}).json()

    h2 = _other_tenant_auth(client, session_factory, slug="other-cdm-2")
    assert client.get(f"{_base(ws)}/contact-tags", headers=h2).status_code == 404
    assert client.post(f"{_base(ws)}/contact-tags", headers=h2, json={"name": "x"}).status_code == 404
    assert client.patch(f"{_base(ws)}/contact-tags/{tag['id']}", headers=h2, json={
        "name": "hacked",
    }).status_code == 404
    assert client.delete(f"{_base(ws)}/contact-tags/{tag['id']}", headers=h2).status_code == 404


# ── AC-CDM-09: tag create/list + uniqueness + cap ────────────────────────────
def test_create_tag_and_list(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contact-tags", headers=h, json={
        "name": "VIP", "emoji": "⭐", "color": "#F59E0B", "description": "high value",
    })
    assert res.status_code == 201
    listed = client.get(f"{_base(ws)}/contact-tags", headers=h).json()
    assert any(t["name"] == "VIP" and t["contactsCount"] == 0 for t in listed)

    dup = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "vip"})
    assert dup.status_code == 422
    assert "name" in dup.json()["detail"]["fieldErrors"]


def test_tag_cap_500_per_workspace(client, session_factory):
    from modules.omnichannel.models import ContactTag

    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    for i in range(500):
        db.add(ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name=f"tag{i}"))
    db.commit()
    db.close()

    res = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "oneMore"})
    assert res.status_code == 422


# ── AC-CDM-10: tagIds replace-set + cross-workspace 422 + no write ───────────
def test_patch_contact_tag_ids_replace_and_cross_workspace_rejected(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    other_ws = client.post("/omnichannel/workspaces", headers=h, json={"name": "Other WS 2"}).json()["id"]

    tag_a = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "A"}).json()
    tag_b = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "B"}).json()
    foreign_tag = client.post(f"{_base(other_ws)}/contact-tags", headers=h, json={"name": "Foreign"}).json()

    cid = _seed_thread(session_factory, name="Tag Replace")

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "tagIds": [tag_a["id"], tag_b["id"]],
    })
    assert res.status_code == 200
    assert {t["id"] for t in res.json()["tags"]} == {tag_a["id"], tag_b["id"]}

    # replace-set: sending just tag_a drops tag_b
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"tagIds": [tag_a["id"]]})
    assert res.status_code == 200
    assert {t["id"] for t in res.json()["tags"]} == {tag_a["id"]}

    # cross-workspace tag id → 422, no write
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "tagIds": [tag_a["id"], foreign_tag["id"]],
    })
    assert res.status_code == 422
    assert "tagIds" in res.json()["detail"]["fieldErrors"]
    after = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert {t["id"] for t in after["tags"]} == {tag_a["id"]}  # unchanged


# ── AC-CDM-11: tag delete removes links only ─────────────────────────────────
def test_delete_tag_removes_links_contact_unaffected(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    tag = client.post(f"{_base(ws)}/contact-tags", headers=h, json={"name": "ToDelete"}).json()
    cid = _seed_thread(session_factory, name="Tag Delete")
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"tagIds": [tag["id"]]})

    res = client.delete(f"{_base(ws)}/contact-tags/{tag['id']}", headers=h)
    assert res.status_code == 204

    after = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert after["tags"] == []
    assert after["name"] == "Tag Delete"  # contact itself untouched


# ── AC-CDM-12: thread list + detail carry tags ───────────────────────────────
def test_thread_list_and_detail_carry_tags(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    tag = client.post(f"{_base(ws)}/contact-tags", headers=h, json={
        "name": "Featured", "emoji": "⭐", "color": "#111111",
    }).json()
    cid = _seed_thread(session_factory, name="Tag Thread List", messages=[{}])
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"tagIds": [tag["id"]]})

    listed = client.get("/omnichannel/contacts", headers=h).json()["data"]
    row = next(t for t in listed if t["id"] == cid)
    assert row["tags"] == [{"id": tag["id"], "name": "Featured", "emoji": "⭐", "color": "#111111"}]

    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["tags"][0]["name"] == "Featured"


# ── AC-CDM-22/23: workflow entity registration + facts + entity event ───────
def test_omnichannel_contact_workflow_entity_registered_and_facts_resolve(session_factory):
    from app.workflow_engine.entities import get_workflow_entity, record_facts
    from modules.omnichannel.models import Contact, Workspace

    entity = get_workflow_entity("omnichannel_contact")
    assert entity is not None
    assert entity.has_status is True
    assert entity.status_attr == "lifecycle_status_id"
    assert "email" in entity.writable and "first_name" in entity.writable

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="Fact", last_name="Check",
        email="fact@example.com", language="en", country_code="MY", priority="HIGH",
    )
    db.add(contact)
    db.commit()

    facts = record_facts(db, "omnichannel_contact", contact)
    assert facts["record.email"] == "fact@example.com"
    assert facts["record.firstName"] == "Fact"
    assert facts["record.priority"] == "HIGH"
    db.close()


def test_contact_patch_emits_one_updated_entity_event_with_changes_diff(client, session_factory):
    from tests.test_workflow_triggers import _edge, _email, _node, _publish, _runs_for

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.updated", {"entityType": "omnichannel_contact"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    db.close()

    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "notes", "label": "Notes", "type": "text",
    })
    cid = _seed_thread(session_factory, name="Event Diff")

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "firstName": "Renamed", "customFields": {"notes": "hi"},
    })
    assert res.status_code == 200

    db = session_factory()
    runs = _runs_for(db, wid)
    assert len(runs) == 1
    changes = runs[0].trigger_payload_json["changes"]
    assert changes["firstName"]["to"] == "Renamed"
    assert changes["customFields.notes"]["to"] == "hi"
    db.close()

    # A second PATCH that changes nothing fires no additional run.
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"firstName": "Renamed"})
    db = session_factory()
    assert len(_runs_for(db, wid)) == 1
    db.close()


# ── AC-CDM-28: permission gates (403 per write key) ──────────────────────────
def _no_perm_auth(client, session_factory, email="cdm-noperm@example.com"):
    db = session_factory()
    db.add(User(
        tenant_id=DEFAULT_TENANT_ID, email=email, name="No Perm",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    ))
    db.commit()
    db.close()
    return _auth(client, email=email, password="Password123!")


def test_permission_gates_403_without_grants(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    h2 = _no_perm_auth(client, session_factory)

    assert client.post(f"{_base(ws)}/contact-fields", headers=h2, json={
        "key": "x", "label": "X", "type": "text",
    }).status_code == 403
    assert client.post(f"{_base(ws)}/contact-tags", headers=h2, json={"name": "x"}).status_code == 403

    cid = _seed_thread(session_factory, name="Perm Gate")
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h2, json={"firstName": "Nope"})
    assert res.status_code == 403
