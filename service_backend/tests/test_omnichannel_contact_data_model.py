"""Omnichannel contact data model - plan 25 S1 (contact fields registry, tags,
the ONE contact-profile write path). Covers AC-CDM-01..12, 22, 23, 28.

Reuses the existing conversation-test seams (`_seed_thread`, `_auth`) rather
than duplicating fixture setup.
"""
import pytest

from app.models import DEFAULT_TENANT_ID, EmailOutbox, User, UserStatus
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


def test_patch_contact_custom_fields_whole_null_clears_all_registered_values(client, session_factory):
    """Review round 2 finding A - `customFields: null` (the WHOLE value, not a
    per-key null inside an object) clears every REGISTERED field's value in
    one PATCH, and the emitted `omnichannel_contact` `updated` entity event
    carries one `customFields.<key>` change per key actually cleared (never a
    silent no-op)."""
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
    base = f"{_base(ws)}/contact-fields"
    client.post(base, headers=h, json={"key": "ca", "label": "CA", "type": "text"})
    client.post(base, headers=h, json={"key": "cb", "label": "CB", "type": "text"})

    cid = _seed_thread(session_factory, name="Clear All Fields")
    seeded = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "customFields": {"ca": "1", "cb": "2"},
    })
    assert seeded.status_code == 200, seeded.text

    cleared = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["customFields"] == {}

    got = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert got["customFields"] == {}

    db = session_factory()
    runs = _runs_for(db, wid)
    assert len(runs) == 2  # once for the seed PATCH, once for the clear-all
    changes = runs[-1].trigger_payload_json["changes"]
    assert changes["customFields.ca"] == {"from": "1", "to": None}
    assert changes["customFields.cb"] == {"from": "2", "to": None}
    db.close()

    # A second whole-null PATCH (nothing left to clear) fires no extra run.
    noop = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"customFields": None})
    assert noop.status_code == 200
    db = session_factory()
    assert len(_runs_for(db, wid)) == 2
    db.close()


def test_value_counts_and_customfields_read_tolerate_legacy_json_null_blob(client, session_factory):
    """Review round 2 finding B - a LEGACY row whose `custom_fields_json` blob
    is a JSON scalar `null` (predates `custom_fields_json` becoming
    `none_as_null=True`) must not break the registry-intersection read
    (ThreadItem `customFields`) or `value_counts` (list view / delete-
    confirmation copy). Simulated via raw SQL bypassing the ORM's JSON type -
    no code path can write this shape anymore, but old rows can still have it.
    The Postgres `jsonb_typeof(...) = 'object'` guard on `value_counts`/
    `_strip_values` is exercised against live Postgres in phase 2 (SQLite has
    no `jsonb_each`/`jsonb_typeof`, so this suite only covers the Python
    fallback paths)."""
    from sqlalchemy import text

    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "co", "label": "Co", "type": "text",
    })

    cid = _seed_thread(session_factory, name="Legacy Null Blob")
    db = session_factory()
    db.execute(text("UPDATE contacts SET custom_fields_json = 'null' WHERE id = :id"), {"id": cid})
    db.commit()
    db.close()

    got = client.get(f"/omnichannel/contacts/{cid}", headers=h)
    assert got.status_code == 200
    assert got.json()["customFields"] == {}

    listed = client.get(f"{_base(ws)}/contact-fields", headers=h)
    assert listed.status_code == 200
    assert listed.json()[0]["valuesCount"] == 0


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


def test_patch_contact_language_format_is_bcp47_shaped(client, session_factory):
    """B8 (plan-25 round-3 codex triage): `language` used to be validated by
    LENGTH ONLY - any 1-16 char string ("123", "!!!", "xxxx") passed. Tighten
    to a (still cheap, non-exhaustive) BCP-47-SHAPED regex: a 2-3 letter
    primary subtag + optional hyphenated subtags. Full BCP-47 validation is a
    backlog item (a real IANA subtag registry check), not this cheap gate."""
    h = _auth(client)
    cid = _seed_thread(session_factory, name="Lang Format Test")

    for bad in ["123", "!!", "a", "toolongprimarytag"]:
        res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"language": bad})
        assert res.status_code == 422, f"{bad!r} should have been rejected: {res.text}"
        assert "language" in res.json()["detail"]["fieldErrors"]

    for good in ["en", "en-US", "zh-Hans", "zh-Hans-CN"]:
        res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"language": good})
        assert res.status_code == 200, f"{good!r} should have been accepted: {res.text}"
        assert res.json()["language"] == good


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


def test_contact_tag_ref_read_ignores_a_link_pointing_at_another_tenants_tag(client, session_factory):
    """Review round 2 finding C - `refs_for_contacts` scopes the JOINED tag
    row by tenant, not just the link. A planted/corrupt `ContactTagLink`
    pointing at another tenant's tag id (the polymorphic stored-id rule -
    never resolve a stored id unscoped) must render NO tag on this contact,
    never that tenant's name/emoji/color."""
    from modules.omnichannel.models import ContactTag, ContactTagLink

    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_thread(session_factory, name="Cross Tenant Tag Link")

    h2 = _other_tenant_auth(client, session_factory, slug="other-cdm-tagref")
    other_tenant_id = _tenant_id_for(session_factory, "other-cdm-tagref")

    db = session_factory()
    foreign_tag = ContactTag(tenant_id=other_tenant_id, workspace_id=ws, name="SecretTag")
    db.add(foreign_tag)
    db.commit()
    db.add(ContactTagLink(tenant_id=DEFAULT_TENANT_ID, contact_id=cid, tag_id=foreign_tag.id))
    db.commit()
    db.close()

    got = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert got["tags"] == []
    listed = client.get("/omnichannel/contacts", headers=h).json()["data"]
    row = next(t for t in listed if t["id"] == cid)
    assert row["tags"] == []


def _tenant_id_for(session_factory, slug: str) -> str:
    from app.models import Tenant

    db = session_factory()
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    db.close()
    return tenant.id


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


def test_resolve_or_create_by_name_recovers_from_concurrent_create_race(session_factory):
    """Review round 2 finding D - two concurrent gateway PATCHes creating the
    SAME unknown tag name can both pass the `_find_by_name` SELECT before
    either INSERTs; the loser's `flush()` then hits the DB backstop
    (`uq_contact_tags_workspace_name`, Postgres functional unique index) and
    used to raise `IntegrityError` straight into the caller as a 500.

    Simulates the race directly (SQLite has no such unique index, so a real
    race can't be reproduced here - only the recovery logic is under test):
    the WINNER's row is pre-committed (as if a concurrent request already
    landed it), our first `_find_by_name` is patched to still miss it (the
    race window before that commit was visible to our own SELECT), and our
    `flush()` is patched to raise `IntegrityError` once (what the DB
    constraint would raise for real). The loser must re-look-up and reuse the
    winner's id, never duplicate the tag or propagate the error."""
    from modules.omnichannel.models import ContactTag, Workspace
    from modules.omnichannel.services.contact_tag_service import ContactTagService
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    winner = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Urgent")
    db.add(winner)
    db.commit()

    svc = ContactTagService(db)
    real_find = svc._find_by_name
    calls = {"n": 0}

    def fake_find(workspace_id, tenant_id, name):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # our SELECT missed the not-yet-visible concurrent insert
        return real_find(workspace_id, tenant_id, name)

    svc._find_by_name = fake_find

    real_flush = db.flush
    flushed = {"n": 0}

    def fake_flush(*a, **kw):
        flushed["n"] += 1
        if flushed["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_flush(*a, **kw)

    db.flush = fake_flush

    ids = svc.resolve_or_create_by_name(ws.id, DEFAULT_TENANT_ID, ["Urgent"])
    assert ids == [winner.id]

    db.flush = real_flush
    total = (
        db.query(ContactTag)
        .filter(ContactTag.tenant_id == DEFAULT_TENANT_ID, ContactTag.workspace_id == ws.id)
        .count()
    )
    assert total == 1  # no duplicate row was left behind by the rolled-back savepoint


def test_resolve_or_create_by_name_batch_race_does_not_orphan_earlier_names(session_factory):
    """B10 (plan-25 round-3 codex triage): resolving MULTIPLE new names in one
    call used to flush+append an id per name IN THE SAME LOOP - a race on a
    LATER name triggered a full `self.db.rollback()`, which discarded the row
    (and id) already flushed for an EARLIER name in the SAME call, while
    `ids` had already captured that (now nonexistent) id -> a dangling
    `tag_id` in `ContactTagLink` / an FK failure on commit.

    Fixed: resolve ALL names in a lookup pass, batch-create only the missing
    ones, and on a race roll back the WHOLE (nothing-else-written) batch and
    RESTART resolution from the lookup pass (bounded retries) - no id is ever
    returned for a row whose flush didn't actually stick.

    Simulates the race directly (SQLite has no functional unique index on
    `contact_tags`, so a real concurrent race can't be reproduced here - only
    the recovery logic is under test): "Bravo" is pre-committed (as if a
    concurrent request already landed it), the FIRST lookup pass is patched
    to miss everything (the race window before that commit was visible to
    our own SELECT), and the FIRST `flush()` is patched to raise
    `IntegrityError` once (what the DB constraint would raise for real for
    the whole batch insert). The retry's lookup pass then finds "Bravo" and
    only needs to create "Alpha" - both names must resolve to exactly one
    row each, with "Bravo" reusing the pre-existing winner's id."""
    from modules.omnichannel.models import ContactTag, Workspace
    from modules.omnichannel.services.contact_tag_service import ContactTagService
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    winner = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Bravo")
    db.add(winner)
    db.commit()
    winner_id = winner.id

    svc = ContactTagService(db)
    real_lookup = svc._find_all_by_names
    lookups = {"n": 0}

    def fake_lookup(workspace_id, tenant_id, names):
        lookups["n"] += 1
        if lookups["n"] == 1:
            return {}  # our lookup pass missed EVERYTHING, incl. the winner
        return real_lookup(workspace_id, tenant_id, names)

    svc._find_all_by_names = fake_lookup

    real_flush = db.flush
    flushed = {"n": 0}

    def fake_flush(*a, **kw):
        flushed["n"] += 1
        if flushed["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_flush(*a, **kw)

    db.flush = fake_flush

    ids = svc.resolve_or_create_by_name(ws.id, DEFAULT_TENANT_ID, ["Alpha", "Bravo"])

    db.flush = real_flush
    rows = db.query(ContactTag).filter(ContactTag.workspace_id == ws.id).all()
    by_id = {r.id: r.name for r in rows}
    assert len(rows) == 2  # exactly Alpha + Bravo - no dangling row, no duplicate
    assert set(ids) == set(by_id.keys())
    assert winner_id in ids  # Bravo reused the pre-existing winner, not a fresh row
    assert by_id[winner_id] == "Bravo"


def test_resolve_or_create_by_name_gives_up_after_bounded_retries(session_factory):
    """B10: a persistent (not just one-shot) flush failure must raise a clean
    validation error, never loop forever or leak the raw `IntegrityError`."""
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.contact_tag_service import (
        ContactTagService,
        TagValidationError,
    )
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    svc = ContactTagService(db)

    def always_miss(workspace_id, tenant_id, names):
        return {}

    def always_raise(*a, **kw):
        raise IntegrityError("insert", {}, Exception("duplicate key value"))

    svc._find_all_by_names = always_miss
    db.flush = always_raise

    with pytest.raises(TagValidationError):
        svc.resolve_or_create_by_name(ws.id, DEFAULT_TENANT_ID, ["Persistent"])


def test_contact_field_create_race_is_a_422_not_a_500(session_factory):
    """B6 (plan-25 round-3 codex triage): the app-level `_find_by_key` check
    passes, then a concurrent request's row lands first - the DB backstop
    (`uq_contact_fields_workspace_key`, Postgres functional unique index)
    raises `IntegrityError` on our `commit()`. That must surface as the SAME
    422 `{fieldErrors: {key: ...}}` a same-request duplicate gets, never an
    unhandled 500. Simulated directly (SQLite has no such index): patch
    `_find_by_key` to miss (the race window) and `db.commit()` to raise once."""
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.contact_field_service import (
        ContactFieldService,
        FieldValidationError,
    )
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    svc = ContactFieldService(db)
    svc._find_by_key = lambda *a, **k: None

    real_commit = db.commit
    calls = {"n": 0}

    def fake_commit(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_commit(*a, **kw)

    db.commit = fake_commit

    class Payload:
        key = "racyField"
        type = "text"
        label = "Racy"
        description = None
        options = None
        visibility = "always"

    with pytest.raises(FieldValidationError) as exc_info:
        svc.create(ws.id, DEFAULT_TENANT_ID, Payload())
    assert "key" in exc_info.value.errors

    db.commit = real_commit
    from modules.omnichannel.models import ContactField

    assert (
        db.query(ContactField.id)
        .filter(ContactField.workspace_id == ws.id, ContactField.key == "racyField")
        .count()
        == 0
    )  # the failed insert was rolled back, not left half-applied


def test_contact_tag_create_race_is_a_422_not_a_500(session_factory):
    """B9 (plan-25 round-3 codex triage): same class of bug as B6, for tag
    CREATE - `_find_by_name` passes, a concurrent create wins the DB
    backstop, our `commit()` raises `IntegrityError`. Must 422, never 500."""
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.contact_tag_service import (
        ContactTagService,
        TagValidationError,
    )
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    svc = ContactTagService(db)
    svc._find_by_name = lambda *a, **k: None

    real_commit = db.commit
    calls = {"n": 0}

    def fake_commit(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_commit(*a, **kw)

    db.commit = fake_commit

    class Payload:
        name = "Racy Tag"
        emoji = None
        color = None
        description = None

    with pytest.raises(TagValidationError) as exc_info:
        svc.create(ws.id, DEFAULT_TENANT_ID, Payload())
    assert exc_info.value.field == "name"

    db.commit = real_commit
    from modules.omnichannel.models import ContactTag

    assert (
        db.query(ContactTag.id)
        .filter(ContactTag.workspace_id == ws.id, ContactTag.name == "Racy Tag")
        .count()
        == 0
    )


def test_contact_tag_rename_race_is_a_422_not_a_500(session_factory):
    """B9: same class of bug for tag RENAME (update) - a concurrent rename to
    the same target name wins the DB backstop; our `commit()` raises."""
    from modules.omnichannel.models import ContactTag, Workspace
    from modules.omnichannel.services.contact_tag_service import (
        ContactTagService,
        TagValidationError,
    )
    from sqlalchemy.exc import IntegrityError

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    row = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name="Original")
    db.add(row)
    db.commit()
    row_id = row.id

    svc = ContactTagService(db)
    svc._find_by_name = lambda *a, **k: None

    real_commit = db.commit
    calls = {"n": 0}

    def fake_commit(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key value"))
        return real_commit(*a, **kw)

    db.commit = fake_commit

    class Payload:
        model_fields_set = {"name"}
        name = "Renamed Racy"
        emoji = None
        color = None
        description = None

    with pytest.raises(TagValidationError) as exc_info:
        svc.update(row_id, ws.id, DEFAULT_TENANT_ID, Payload())
    assert exc_info.value.field == "name"

    db.commit = real_commit
    db.refresh(row)
    assert row.name == "Original"  # the failed rename was rolled back


# ── Review round 1, finding 11: pinned wire types (visibility / color) ──────
def test_contact_field_visibility_rejects_unknown_value(client):
    """`visibility` is a `Literal["always","hidden"]` at the wire boundary
    (foolproof-UI - a picker must only offer valid options) - Pydantic 422s
    before the request ever reaches the service."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "sourceX", "label": "Source X", "type": "text", "visibility": "banana",
    })
    assert res.status_code == 422, res.text


def test_contact_tag_color_rejects_non_hex_value(client):
    """`color` must be a 6-digit hex value - the native `<input type=color>`
    only ever emits one, and a non-hex string would render straight into the
    tag chip's inline `style` on the frontend."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contact-tags", headers=h, json={
        "name": "Bad Color", "color": "not-a-color",
    })
    assert res.status_code == 422, res.text

    ok = client.post(f"{_base(ws)}/contact-tags", headers=h, json={
        "name": "Good Color", "color": "#abcdef",
    })
    assert ok.status_code == 201, ok.text

    update_bad = client.patch(f"{_base(ws)}/contact-tags/{ok.json()['id']}", headers=h, json={
        "color": "red",
    })
    assert update_bad.status_code == 422, update_bad.text


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
    # `has_status=False` deliberately (review round 1, finding 7) - the
    # entity's `entity_type` doesn't match the workspace-scoped
    # `omnichannel_contact_lifecycle` status entity, so a naive True produced
    # an empty status picker + a runtime `UnknownStatusEntity`.
    # `status_attr` is kept as harmless metadata for a future fix.
    assert entity.has_status is False
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


def test_internal_patch_emits_entity_event_with_real_actor_name_and_email(client, session_factory):
    """Review round 2 finding L - the internal PATCH (`routers/conversations.
    py patch_thread`) passed `actor_id=` but never `actor=` to `ConversationService.
    patch_thread`, so the emitted `omnichannel_contact` `updated` event's actor
    always had blank `name`/`email` (only `id`) - a workflow rendering
    `{{ trigger.actor.name }}` in a notification would show nothing. The actor
    must carry the real logged-in user's name/email, resolved the same way the
    lifecycle-move path already does (`resolve_native_actor`)."""
    from tests.test_workflow_triggers import _edge, _email, _node, _publish, _runs_for

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.updated", {"entityType": "omnichannel_contact"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    db.close()

    h = _auth(client)
    cid = _seed_thread(session_factory, name="Actor Diff")
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"firstName": "Actorful"})
    assert res.status_code == 200

    db = session_factory()
    runs = _runs_for(db, wid)
    assert len(runs) == 1
    actor = runs[0].trigger_payload_json["actor"]
    assert actor["email"] == ACTIVE_EMAIL
    assert actor["name"]  # non-empty - the real user's display name
    db.close()


def test_field_changed_trigger_matches_omnichannel_contacts_camelcase_change_keys(
    client, session_factory
):
    """B7 (plan-25 round-3 codex triage): `ContactProfileService.patch` emits
    `omnichannel_contact` `updated` events with WIRE (camelCase) `changes`
    keys (`firstName`, `customFields.<key>`) per AC-23 - deliberately kept,
    not a bug. But `entity.field_changed`'s refinement canonicalized ONLY the
    configured field through `attr_for` (camelCase -> snake_case) before
    comparing it against the raw `changes` keys, so a trigger configured for
    `firstName` compared `attr_for("firstName")` == `"first_name"` against a
    `changes` dict that actually holds `"firstName"` - never matched. Fixed by
    canonicalizing BOTH sides through the same `attr_for`, so a field-specific
    trigger fires for a plain field (`firstName`) AND a dotted custom-field
    key (`customFields.<key>`)."""
    from tests.test_workflow_triggers import _edge, _email, _node, _publish, _runs_for

    db = session_factory()
    doc_first_name = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.field_changed", {
            "entityType": "omnichannel_contact", "field": "firstName",
        }),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid_first_name = _publish(db, doc_first_name)
    db.close()

    h = _auth(client)
    ws = _workspace_id(client, h)
    field = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "notes", "label": "Notes", "type": "text",
    })
    assert field.status_code == 201, field.text
    cid = _seed_thread(session_factory, name="Field Changed Trigger")

    # Unrelated field changes - must NOT fire the firstName-specific trigger.
    client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"lastName": "Nope"})
    db = session_factory()
    assert len(_runs_for(db, wid_first_name)) == 0
    db.close()

    # firstName changes - must fire.
    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={"firstName": "Matched"})
    assert res.status_code == 200, res.text
    db = session_factory()
    assert len(_runs_for(db, wid_first_name)) == 1
    db.close()

    # A dotted customFields.<key> trigger must also match.
    db = session_factory()
    doc_custom = {"schemaVersion": 1, "nodes": [
        _node("trg2", "trigger", "entity.field_changed", {
            "entityType": "omnichannel_contact", "field": "customFields.notes",
        }),
        _email("b"),
    ], "edges": [_edge("trg2", "b")]}
    wid_custom = _publish(db, doc_custom)
    db.close()

    res = client.patch(f"/omnichannel/contacts/{cid}", headers=h, json={
        "customFields": {"notes": "hello"},
    })
    assert res.status_code == 200, res.text
    db = session_factory()
    assert len(_runs_for(db, wid_custom)) == 1
    db.close()


def test_workflow_entity_update_on_contact_validates_and_fans_out_webhook(client, session_factory):
    """B11 (plan-25 round-3 codex triage): `entity.update` used to write
    rendered strings straight onto `Contact` columns via `setattr`, bypassing
    BOTH the contact-profile validation (`language`/`countryCode` format +
    normalization) AND the realtime/webhook `contact.updated` fan-out every
    OTHER contact write path gets. Fixed via `WorkflowEntity.apply_update`
    routing through `ConversationService.patch_thread` (validation +
    normalization + ONE `contact.updated` event + realtime + webhook - the
    SAME seam the internal PATCH and the public gateway PATCH both use)."""
    from app.services.workflow_service import WorkflowService
    from modules.omnichannel.models import Contact, WebhookDelivery
    from tests.test_omnichannel_api_gateway import _seeded
    from tests.test_workflow_triggers import _actor, _edge, _node, _publish

    hdr, cid = _seeded(client, session_factory, phone="+60177000011")
    reg = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "w", "url": "https://hooks.example.com/w", "events": ["contact.updated"]},
        headers=hdr,
    )
    assert reg.status_code == 201, reg.text

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": []}),
        _node("upd", "action", "entity.update", {
            "entityType": "omnichannel_contact", "recordId": cid,
            "assignments": [{"field": "countryCode", "value": "my"}],
        }),
    ], "edges": [_edge("trg", "upd")]}
    wid = _publish(db, doc)
    run = WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={}, is_test=False, actor=_actor(db))
    assert run.status == "success", run.error

    contact = db.query(Contact).filter(Contact.id == cid).first()
    assert contact.country_code == "MY"  # normalized, not the raw rendered "my"

    delivery = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.event_type == "contact.updated")
        .order_by(WebhookDelivery.created_at.desc())
        .first()
    )
    assert delivery is not None  # exactly one contact.updated fan-out
    assert delivery.payload_json["data"]["contact"]["countryCode"] == "MY"
    db.close()


def test_workflow_entity_update_on_contact_rejects_invalid_value(session_factory):
    """B11: an invalid value must FAIL the node (through the SAME validation
    every other write path enforces), never write straight through."""
    from app.services.workflow_service import WorkflowService
    from modules.omnichannel.models import Contact
    from tests.test_workflow_triggers import _actor, _edge, _node, _publish

    cid = _seed_thread(session_factory, name="Invalid CC Test")
    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "manual", {"inputs": []}),
        _node("upd", "action", "entity.update", {
            "entityType": "omnichannel_contact", "recordId": cid,
            "assignments": [{"field": "countryCode", "value": "not-a-code"}],
        }),
    ], "edges": [_edge("trg", "upd")]}
    wid = _publish(db, doc)
    run = WorkflowService(db).run(wid, DEFAULT_TENANT_ID, inputs={}, is_test=False, actor=_actor(db))
    assert run.status == "failed"

    contact = db.query(Contact).filter(Contact.id == cid).first()
    assert contact.country_code is None  # rejected value never applied
    db.close()


def test_internal_patch_rejects_phone(client, session_factory):
    """Review round 1, finding 12 - `phone` is the inbound stitch key (no
    uniqueness guard, outside the AC-22 whitelist) and must never be
    writable through the internal thread PATCH, even alongside a legitimate
    field (nothing should be applied on the 422)."""
    h = _auth(client)
    cid = _seed_thread(session_factory, name="Phone Guard")

    res = client.patch(
        f"/omnichannel/contacts/{cid}", headers=h, json={"phone": "+60199999999"}
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["fieldErrors"]["phone"]

    # Mixed with a field that WOULD otherwise be valid - the whole PATCH is
    # still rejected (phone is checked before anything is applied).
    mixed = client.patch(
        f"/omnichannel/contacts/{cid}",
        headers=h,
        json={"firstName": "Should Not Apply", "phone": "+60199999999"},
    )
    assert mixed.status_code == 422, mixed.text
    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["firstName"] != "Should Not Apply"


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


# =============================================================================
# Plan 25 S2 - contact lifecycle on the (scoped) status engine
# Covers AC-CDM-13..21, 24 (+ the S2 slice of AC-CDM-40).
# =============================================================================

LIFECYCLE_ENTITY = "omnichannel_contact_lifecycle"
_SEED_KEYS = {"new_lead", "hot_lead", "payment", "customer", "cold_lead"}


def _lifecycle_graph(client, h, ws_id):
    res = client.get(
        "/statuses", params={"entityType": LIFECYCLE_ENTITY, "scopeId": ws_id}, headers=h
    )
    assert res.status_code == 200, res.text
    return res.json()


def _stage_ids(graph):
    return {s["key"]: s["id"] for s in graph["statuses"]}


def _seed_lifecycle_contact(session_factory, ws_id, tenant_id=DEFAULT_TENANT_ID, name="Lifecycle Test"):
    """A contact stamped with its workspace's initial lifecycle stage."""
    from modules.omnichannel.services.lifecycle_service import initial_status_id

    cid = _seed_thread(session_factory, name=name)
    db = session_factory()
    from modules.omnichannel.models import Contact

    contact = db.query(Contact).filter(Contact.id == cid).first()
    contact.workspace_id = ws_id
    contact.tenant_id = tenant_id
    contact.lifecycle_status_id = initial_status_id(db, tenant_id, ws_id)
    db.commit()
    db.close()
    return cid


# ── AC-CDM-13: registration + scoped canvas API ──────────────────────────────
def test_lifecycle_entity_registered_and_canvas_returns_workspace_graph(client):
    from app.status_engine.registry import get_status_entity

    entity = get_status_entity(LIFECYCLE_ENTITY)
    assert entity is not None
    assert entity.module == "omnichannel"
    assert entity.scoped is True
    assert entity.scope_attr == "workspace_id"
    assert entity.scope_label == "Workspace"
    assert entity.status_attr == "lifecycle_status_id"
    assert set(entity.required_flags) == {"is_initial", "is_terminal", "is_archived"}

    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    assert {s["key"] for s in graph["statuses"]} == _SEED_KEYS
    new_lead = next(s for s in graph["statuses"] if s["key"] == "new_lead")
    assert new_lead["isInitial"] is True and "🆕" in new_lead["label"]
    customer = next(s for s in graph["statuses"] if s["key"] == "customer")
    assert customer["isTerminal"] is True
    cold = next(s for s in graph["statuses"] if s["key"] == "cold_lead")
    assert cold["isArchived"] is True
    # mesh(6) + each-active->customer(3) + each-active->cold_lead(3) + cold_lead->new_lead(1)
    assert len(graph["transitions"]) == 13
    assert all(t["label"].startswith("Move to ") for t in graph["transitions"])


def test_lifecycle_canvas_tenant_isolation(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    h2 = _other_tenant_auth(client, session_factory, slug="other-cdm-lifecycle")
    res = client.get(
        "/statuses", params={"entityType": LIFECYCLE_ENTITY, "scopeId": ws}, headers=h2
    )
    assert res.status_code == 404


# ── AC-CDM-14: materialized at workspace creation + install_tenant ──────────
def test_workspace_create_materializes_lifecycle_same_transaction(client):
    h = _auth(client)
    res = client.post("/omnichannel/workspaces", headers=h, json={"name": "New WS For Lifecycle"})
    assert res.status_code == 201, res.text
    ws_id = res.json()["id"]
    graph = _lifecycle_graph(client, h, ws_id)
    assert {s["key"] for s in graph["statuses"]} == _SEED_KEYS
    assert all(s["id"] for s in graph["statuses"])


def test_install_tenant_default_workspace_already_has_lifecycle_graph(client):
    # conftest installs omnichannel via AppStoreService (the real install_tenant
    # path) - the default workspace must already carry a graph.
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    assert len(graph["statuses"]) == 5


def test_install_tenant_backfills_when_default_workspace_predates_the_graph(session_factory):
    """Review round 1, finding 17: `install_tenant`'s pre-existing-workspace
    branch used to early-return with NOTHING materialized. Simulate exactly
    that: a DEFAULT workspace that predates the lifecycle graph (created
    directly, bypassing `WorkspaceService`) + a contact with no
    `lifecycle_status_id`. Re-running `install_tenant` (self-heal path, e.g.
    a repeat App-Store install call) must materialize the graph AND stamp the
    contact - not silently no-op."""
    from modules.omnichannel.bootstrap import install_tenant
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services.lifecycle_service import stages_for_workspace

    db = session_factory()
    default_ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    ws_id = default_ws.id
    # Wipe out the graph conftest's real install already materialized, so this
    # test starts from the exact "predates the graph" state the finding
    # describes, then adds an un-stamped contact.
    from modules.omnichannel.services.lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY
    from app.models.status import Status as CoreStatus
    from app.models.status_transition import StatusTransition

    db.query(StatusTransition).filter(
        StatusTransition.entity_type == LIFECYCLE_ENTITY, StatusTransition.tenant_id == DEFAULT_TENANT_ID
    ).delete(synchronize_session=False)
    db.query(CoreStatus).filter(
        CoreStatus.entity_type == LIFECYCLE_ENTITY, CoreStatus.scope_id == ws_id
    ).delete(synchronize_session=False)
    legacy_contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, first_name="Predates")
    db.add(legacy_contact)
    db.commit()
    contact_id = legacy_contact.id
    assert stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id) == []
    db.close()

    db = session_factory()
    install_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    stages = stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)
    assert {s.key for s in stages} == _SEED_KEYS
    initial = next(s for s in stages if s.is_initial)
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    assert contact.lifecycle_status_id == initial.id
    db.close()

    # Re-running again is a no-op (idempotent self-heal).
    db = session_factory()
    install_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    assert len(stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)) == 5
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    assert contact.lifecycle_status_id == initial.id
    db.close()


# ── AC-CDM-15: update_tenant backfill + idempotent re-run ───────────────────
def test_update_tenant_backfill_materializes_and_stamps_then_noops(session_factory):
    from modules.omnichannel.bootstrap import update_tenant
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.lifecycle_service import stages_for_workspace

    db = session_factory()
    # A workspace created directly (bypassing WorkspaceService) - simulates a
    # tenant that predates this slice.
    legacy_ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Legacy WS",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
        is_default=False, is_trashed=False,
    )
    db.add(legacy_ws)
    db.flush()
    legacy_contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=legacy_ws.id, first_name="Legacy")
    db.add(legacy_contact)
    db.commit()
    ws_id, contact_id = legacy_ws.id, legacy_contact.id
    assert stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id) == []
    db.close()

    db = session_factory()
    update_tenant(db, DEFAULT_TENANT_ID, "0.1.0")
    db.commit()
    stages = stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)
    assert {s.key for s in stages} == _SEED_KEYS
    initial = next(s for s in stages if s.is_initial)
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    assert contact.lifecycle_status_id == initial.id
    db.close()

    # Re-running is a no-op: no duplicate graph, contact untouched.
    db = session_factory()
    update_tenant(db, DEFAULT_TENANT_ID, "0.2.0")
    db.commit()
    assert len(stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)) == 5
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    assert contact.lifecycle_status_id == initial.id
    db.close()


# ── AC-CDM-16: every contact-creation path sets the initial stage ───────────
def test_inbound_stitch_sets_initial_lifecycle_stage(session_factory):
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.inbound_service import InboundService
    from modules.omnichannel.services.lifecycle_service import initial_status_id

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    channel = Channel(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, channel_type="WHATSAPP",
        name="Inbound Lifecycle Test", credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id="pn-lifecycle-inbound", is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.flush()

    contact = InboundService(db)._resolve_contact(
        channel, {"from": "60129998877", "profile_name": "Fresh Lead"}
    )
    db.commit()

    expected = initial_status_id(db, DEFAULT_TENANT_ID, ws.id)
    assert expected is not None
    assert contact.lifecycle_status_id == expected
    db.close()


def test_gateway_contact_creation_sets_initial_lifecycle_stage(session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services.lifecycle_service import initial_status_id
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    contact = PublicGatewayService(db)._resolve_or_create_contact(
        DEFAULT_TENANT_ID, ws.id, "+60129998866"
    )
    expected = initial_status_id(db, DEFAULT_TENANT_ID, ws.id)
    assert expected is not None
    assert contact.lifecycle_status_id == expected
    db.close()


def test_dev_seed_demo_contacts_get_initial_lifecycle_stage(session_factory):
    from modules.omnichannel.models import Contact

    db = session_factory()
    ws_id = db.query(Contact.workspace_id).filter(Contact.id == "cnt-001").first()
    if ws_id is None:
        # Dev seed not wired into this suite's default fixture - skip cleanly.
        db.close()
        return
    for cid in ("cnt-001", "cnt-002", "cnt-003", "cnt-004", "cnt-005"):
        c = db.query(Contact).filter(Contact.id == cid).first()
        if c is not None:
            assert c.lifecycle_status_id is not None
    db.close()


# ── AC-CDM-17: move happy path / 409 no-edge / 404 cross-workspace+tenant /
#    edge-role auth / notification fires ────────────────────────────────────
def test_move_lifecycle_happy_path(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws)

    res = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids["hot_lead"],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lifecycle"]["key"] == "hot_lead"
    assert body["lifecycle"]["isWon"] is False
    assert body["lifecycle"]["isLost"] is False

    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["lifecycle"]["statusId"] == ids["hot_lead"]


def test_move_lifecycle_impersonation_authorizes_as_effective_user(client, session_factory):
    """B5 (plan-25 round-3 codex triage): edge-role/condition authorization for
    a lifecycle move must run as the EFFECTIVE (impersonated target) user, not
    the real admin - `status_machine.transition`'s `actor` param is an
    AUTHORIZATION identity everywhere else in the codebase (form_service,
    tenant_service, ideation all pass the effective `current_user`), never the
    real-admin attribution id. Condition the new_lead->hot_lead edge on
    `actor.email == <target's email>` - the move must SUCCEED while
    impersonating that target (their identity is what gets checked) even
    though the real admin's own email never matches the condition."""
    from app.models import Role
    from app.models.status_transition import StatusTransition
    from app.repositories.permission_repository import PermissionRepository
    from tests.test_status_engine import _cond, _group

    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws)

    target_email = "impersonated-lifecycle@example.com"
    db = session_factory()
    # A role that can reach the endpoint (`contacts.manage`) but deliberately
    # WITHOUT `users.impersonate` (a user who can also impersonate can't be
    # impersonated - `ImpersonationService.start`).
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Lifecycle Mover")
    role.permissions = PermissionRepository(db).get_by_keys(["contacts.manage"])
    db.add(role)
    db.flush()
    target = User(
        tenant_id=DEFAULT_TENANT_ID, email=target_email, name="Impersonated Target",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    )
    target.roles = [role]
    db.add(target)
    db.flush()
    target_id = target.id

    edge = (
        db.query(StatusTransition)
        .filter(
            StatusTransition.entity_type == LIFECYCLE_ENTITY,
            StatusTransition.tenant_id == DEFAULT_TENANT_ID,
            StatusTransition.from_status_id == ids["new_lead"],
            StatusTransition.to_status_id == ids["hot_lead"],
        )
        .first()
    )
    assert edge is not None
    edge.conditions_json = _group(_cond("actor.email", "eq", target_email))
    db.commit()
    db.close()

    start = client.post(
        "/impersonation/start", headers=h, json={"targetUserId": target_id}
    )
    assert start.status_code == 200, start.text
    headers = {**h, "X-Impersonate-User-Id": target_id}

    # Real admin's own email never satisfies the condition - if the bug
    # regresses (actor=real admin) this 409s instead of succeeding.
    res = client.post(
        f"/omnichannel/contacts/{cid}/lifecycle",
        headers=headers,
        json={"toStatusId": ids["hot_lead"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["lifecycle"]["key"] == "hot_lead"


def test_move_lifecycle_no_edge_409(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws)

    # new_lead -> customer (won) is a valid edge.
    won = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids["customer"],
    })
    assert won.status_code == 200, won.text
    assert won.json()["lifecycle"]["isWon"] is True

    # customer is terminal - no outgoing edges at all.
    res = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids["new_lead"],
    })
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "lifecycle_move_not_allowed"

    # Nothing was written by the failed move.
    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["lifecycle"]["key"] == "customer"


def test_move_lifecycle_cross_workspace_and_cross_tenant_404(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_lifecycle_contact(session_factory, ws)

    # Another workspace, same tenant - its stage ids belong to a DIFFERENT scope.
    other_ws = client.post("/omnichannel/workspaces", headers=h, json={"name": "Other Lifecycle WS"}).json()["id"]
    other_graph = _lifecycle_graph(client, h, other_ws)
    other_ids = _stage_ids(other_graph)
    res = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": other_ids["hot_lead"],
    })
    assert res.status_code == 404, res.text

    # A stage id belonging to another TENANT's own workspace.
    h2 = _other_tenant_auth(client, session_factory, slug="other-cdm-lifecycle-2")
    ws2 = _workspace_id(client, h2)
    graph2 = _lifecycle_graph(client, h2, ws2)
    ids2 = _stage_ids(graph2)
    res2 = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids2["hot_lead"],
    })
    assert res2.status_code == 404, res2.text

    # And the contact itself is invisible cross-tenant (uniform 404, never data).
    res3 = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h2, json={
        "toStatusId": ids2["hot_lead"],
    })
    assert res3.status_code == 404, res3.text


def test_move_lifecycle_edge_role_auth(session_factory):
    """Direct-service test (mirrors `test_edge_roles_gate_who_can_fire` in
    `test_status_engine.py`) - gate one edge behind the Admin role, then a
    roleless actor is forbidden while the Admin succeeds."""
    from app.models import Role
    from app.models.status_transition import StatusTransition
    from app.services.status_machine import TransitionForbidden
    from modules.omnichannel.models import Contact, Workspace
    from modules.omnichannel.services.lifecycle_service import move, stages_for_workspace

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    stages = {s.key: s for s in stages_for_workspace(db, DEFAULT_TENANT_ID, ws.id)}
    edge = (
        db.query(StatusTransition)
        .filter(
            StatusTransition.entity_type == LIFECYCLE_ENTITY,
            StatusTransition.from_status_id == stages["new_lead"].id,
            StatusTransition.to_status_id == stages["hot_lead"].id,
        )
        .first()
    )
    admin_role = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin").first()
    edge.roles = [admin_role]
    db.commit()

    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    bystander = User(
        tenant_id=DEFAULT_TENANT_ID, email="lifecycle-bystander@example.com",
        password=hash_password("Password123!"), name="No Roles", status=UserStatus.ACTIVE.value,
    )
    db.add(bystander)
    db.commit()

    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="Role Gated",
        lifecycle_status_id=stages["new_lead"].id,
    )
    db.add(contact)
    db.commit()

    with pytest.raises(TransitionForbidden):
        move(db, contact, stages["hot_lead"].id, actor=bystander)
    move(db, contact, stages["hot_lead"].id, actor=admin)
    db.commit()
    assert contact.lifecycle_status_id == stages["hot_lead"].id
    db.close()


def test_move_lifecycle_fires_transition_notification(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    edge = next(
        t for t in graph["transitions"]
        if t["fromStatusId"] == ids["new_lead"] and t["toStatusId"] == ids["hot_lead"]
    )
    res = client.patch(f"/statuses/transitions/{edge['id']}", headers=h, json={
        "notifications": [{
            "channel": "EMAIL",
            "templateSubject": "{{recordLabel}} moved to {{toStatus}}",
            "templateBody": "{{actorName}} performed {{transitionLabel}}.",
            "recipients": [{"targetType": "DYNAMIC", "dynamicKey": "ACTOR"}],
        }],
    })
    assert res.status_code == 200, res.text

    cid = _seed_lifecycle_contact(session_factory, ws)
    db = session_factory()
    before = db.query(EmailOutbox).count()
    db.close()

    move_res = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids["hot_lead"],
    })
    assert move_res.status_code == 200, move_res.text

    db = session_factory()
    rows = db.query(EmailOutbox).offset(before).all()
    assert any(r.to_email == ACTIVE_EMAIL for r in rows)
    db.close()


# ── AC-CDM-18: fireable moves, empty on a won stage ─────────────────────────
def test_lifecycle_moves_list_and_empty_on_won(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws)

    res = client.get(f"/omnichannel/contacts/{cid}/lifecycle-moves", headers=h)
    assert res.status_code == 200, res.text
    moves = res.json()
    assert {m["toStatusId"] for m in moves} == {
        ids["hot_lead"], ids["payment"], ids["customer"], ids["cold_lead"],
    }
    assert all({"edgeId", "toStatusId", "label"} <= set(m) for m in moves)

    client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={"toStatusId": ids["customer"]})
    after = client.get(f"/omnichannel/contacts/{cid}/lifecycle-moves", headers=h)
    assert after.status_code == 200
    assert after.json() == []


# ── AC-CDM-19: thread list + detail carry `lifecycle` ───────────────────────
def test_thread_list_and_detail_carry_lifecycle(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws, name="Lifecycle Thread")

    listed = client.get("/omnichannel/contacts", headers=h).json()["data"]
    row = next(t for t in listed if t["id"] == cid)
    assert row["lifecycle"]["statusId"] == ids["new_lead"]
    assert row["lifecycle"]["key"] == "new_lead"
    assert row["lifecycle"]["isWon"] is False
    assert row["lifecycle"]["isLost"] is False

    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["lifecycle"]["statusId"] == ids["new_lead"]


def test_thread_lifecycle_null_when_unset(client, session_factory):
    cid = _seed_thread(session_factory, name="No Lifecycle Yet")
    h = _auth(client)
    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["lifecycle"] is None


def test_thread_lifecycle_null_when_stage_id_belongs_to_another_workspace(client, session_factory):
    """Review round 1, finding 4 - `_lifecycle_map` resolved a stored
    `lifecycle_status_id` tenant + entity-type scoped but NOT WORKSPACE
    scoped, so a status id that happens to exist for another workspace of the
    SAME tenant (the machine is `scope_id`-per-workspace, ids are otherwise
    ordinary rows) rendered as if it belonged here. Stamp a contact in
    workspace A with a stage id borrowed from workspace B - it must render
    `lifecycle: null`, never B's stage data."""
    h = _auth(client)
    ws_a = _workspace_id(client, h)
    other = client.post("/omnichannel/workspaces", headers=h, json={"name": "Other WS"})
    assert other.status_code == 201, other.text
    ws_b = other.json()["id"]
    graph_b = _lifecycle_graph(client, h, ws_b)
    foreign_stage_id = _stage_ids(graph_b)["hot_lead"]

    cid = _seed_thread(session_factory, name="Cross Workspace Stage")
    from modules.omnichannel.models import Contact

    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    contact.workspace_id = ws_a
    contact.lifecycle_status_id = foreign_stage_id
    db.commit()
    db.close()

    detail = client.get(f"/omnichannel/contacts/{cid}", headers=h).json()
    assert detail["lifecycle"] is None

    listed = client.get("/omnichannel/contacts", headers=h).json()["data"]
    row = next(t for t in listed if t["id"] == cid)
    assert row["lifecycle"] is None


# ── AC-CDM-20: canvas edits apply directly, no fork; delete guard; single
#    is_initial enforced (generic engine fix, not omnichannel-specific) ─────
def test_lifecycle_canvas_edits_apply_directly_no_fork(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)

    # Add a stage.
    created = client.post("/statuses", headers=h, json={
        "entityType": LIFECYCLE_ENTITY, "label": "Nurture", "color": "purple", "scopeId": ws,
    })
    assert created.status_code == 201, created.text
    nurture_id = created.json()["id"]

    # Rename it.
    renamed = client.patch(f"/statuses/{nurture_id}", headers=h, json={"label": "Nurturing"})
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Nurturing"

    # Add an edge from New Lead -> Nurture.
    edge = client.post("/statuses/transitions", headers=h, json={
        "entityType": LIFECYCLE_ENTITY, "fromStatusId": ids["new_lead"],
        "toStatusId": nurture_id, "label": "Move to Nurturing", "scopeId": ws,
    })
    assert edge.status_code == 201, edge.text

    # Reorder.
    all_ids = [s["id"] for s in _lifecycle_graph(client, h, ws)["statuses"]]
    reordered = list(reversed(all_ids))
    res = client.post("/statuses/reorder", headers=h, json={
        "entityType": LIFECYCLE_ENTITY, "orderedIds": reordered, "scopeId": ws,
    })
    assert res.status_code == 200, res.text

    # Deactivate then reactivate (no crash - not part of this entity's flag
    # vocabulary, but the generic action must not error).
    deactivated = client.post(f"/statuses/{nurture_id}/deactivate", headers=h)
    assert deactivated.status_code == 200
    reactivated = client.post(f"/statuses/{nurture_id}/activate", headers=h)
    assert reactivated.status_code == 200

    # Remove the edge.
    del_edge = client.delete(f"/statuses/transitions/{edge.json()['id']}", headers=h)
    assert del_edge.status_code == 204

    # Directly on the scoped rows - no platform fork exists for this entity.
    from app.models.status import Status as CoreStatus

    db = session_factory()
    row = db.query(CoreStatus).filter(CoreStatus.id == nurture_id).first()
    assert row.tenant_id == DEFAULT_TENANT_ID
    assert row.scope_id == ws
    db.close()


def test_lifecycle_delete_guard_blocks_stage_with_contacts(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)
    _seed_lifecycle_contact(session_factory, ws)

    res = client.delete(f"/statuses/{ids['new_lead']}", headers=h)
    assert res.status_code == 409, res.text

    migrated = client.post(f"/statuses/{ids['new_lead']}/migrate-records", headers=h, json={
        "toStatusId": ids["hot_lead"],
    })
    assert migrated.status_code == 200, migrated.text
    assert migrated.json()["migrated"] == 1

    # `new_lead` is `seed_statuses`' sole `isInitial` stage - even with every
    # record migrated off it, the review round 1 finding 6 guard (AC-20:
    # exactly one `isInitial` per set, never zero) still blocks the delete.
    still_initial = client.delete(f"/statuses/{ids['new_lead']}", headers=h)
    assert still_initial.status_code == 422, still_initial.text
    assert "initial" in still_initial.json()["detail"].lower()

    # Once ANOTHER stage takes over as initial, the (now non-initial,
    # record-free) stage is free to be deleted.
    promoted = client.patch(f"/statuses/{ids['hot_lead']}", headers=h, json={
        "flags": {"isInitial": True},
    })
    assert promoted.status_code == 200, promoted.text
    ok = client.delete(f"/statuses/{ids['new_lead']}", headers=h)
    assert ok.status_code == 204, ok.text


def test_lifecycle_exactly_one_is_initial_enforced(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    graph = _lifecycle_graph(client, h, ws)
    ids = _stage_ids(graph)

    # Flip hot_lead to initial - new_lead must silently lose the flag.
    res = client.patch(f"/statuses/{ids['hot_lead']}", headers=h, json={
        "flags": {"isInitial": True},
    })
    assert res.status_code == 200, res.text

    after = _lifecycle_graph(client, h, ws)
    initials = [s for s in after["statuses"] if s["isInitial"]]
    assert len(initials) == 1
    assert initials[0]["key"] == "hot_lead"


# ── AC-CDM-21: uninstall cleans core status rows ────────────────────────────
def test_uninstall_tenant_cleans_core_lifecycle_status_rows(session_factory):
    from app.models.status import Status as CoreStatus
    from app.models.status_transition import StatusTransition
    from app.services.app_store_service import AppStoreService
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    ws_id = ws.id
    before = (
        db.query(CoreStatus)
        .filter(CoreStatus.entity_type == LIFECYCLE_ENTITY, CoreStatus.scope_id == ws_id)
        .count()
    )
    assert before == 5

    AppStoreService(db).uninstall(DEFAULT_TENANT_ID, "omnichannel", "omnichannel")
    db.commit()

    after_statuses = (
        db.query(CoreStatus)
        .filter(CoreStatus.entity_type == LIFECYCLE_ENTITY, CoreStatus.scope_id == ws_id)
        .count()
    )
    after_edges = (
        db.query(StatusTransition)
        .filter(StatusTransition.entity_type == LIFECYCLE_ENTITY, StatusTransition.tenant_id == DEFAULT_TENANT_ID)
        .count()
    )
    assert after_statuses == 0
    assert after_edges == 0
    db.close()


# ── AC-CDM-24: entity.status_changed workflow trigger fires on a move ──────
def test_status_changed_workflow_trigger_fires_on_lifecycle_move(client, session_factory):
    from modules.omnichannel.models import Workspace
    from tests.test_workflow_triggers import _edge, _email, _node, _publish, _runs_for

    db = session_factory()
    doc = {"schemaVersion": 1, "nodes": [
        _node("trg", "trigger", "entity.status_changed", {"entityType": "omnichannel_contact"}),
        _email("a"),
    ], "edges": [_edge("trg", "a")]}
    wid = _publish(db, doc)
    ws_id = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    db.close()

    h = _auth(client)
    graph = _lifecycle_graph(client, h, ws_id)
    ids = _stage_ids(graph)
    cid = _seed_lifecycle_contact(session_factory, ws_id)

    res = client.post(f"/omnichannel/contacts/{cid}/lifecycle", headers=h, json={
        "toStatusId": ids["hot_lead"],
    })
    assert res.status_code == 200, res.text

    db = session_factory()
    runs = _runs_for(db, wid)
    assert len(runs) == 1
    payload = runs[0].trigger_payload_json
    assert payload["fromStatus"] == ids["new_lead"]
    assert payload["toStatus"] == ids["hot_lead"]
    assert payload["recordId"] == cid
    db.close()


# ── Review round 1, finding 7: has_status=False - no broken status picker,
# no UnknownStatusEntity, entity.status_changed unaffected ─────────────────
def test_omnichannel_contact_metadata_has_no_status_picker(client, session_factory):
    """`GET /workflows/metadata` must never advertise a status picker for an
    entity that has none to offer (foolproof-UI) - `omnichannel_contact`'s
    real machine is workspace-scoped, so there is no single tenant-wide list."""
    h = _auth(client)
    res = client.get("/workflows/metadata", headers=h)
    assert res.status_code == 200, res.text
    by_type = {e["type"]: e for e in res.json()["entities"]}
    assert by_type["omnichannel_contact"]["hasStatus"] is False
    assert by_type["omnichannel_contact"]["statuses"] == []


def test_entity_transition_status_action_rejects_omnichannel_contact_cleanly(session_factory):
    """`entity.transition_status` must fail with the standard, caught
    `ActionError` ("has no state machine") - NOT the raw
    `UnknownStatusEntity` that `has_status=True` used to let through when the
    entity's `entity_type` didn't match any registered status entity."""
    from modules.omnichannel.models import Workspace

    from app.workflow_engine.actions.entity_actions import ActionError, entity_transition_status

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    cid = _seed_lifecycle_contact(session_factory, ws.id)
    db.close()

    db = session_factory()
    with pytest.raises(ActionError, match="no state machine"):
        entity_transition_status(
            db,
            DEFAULT_TENANT_ID,
            {"entityType": "omnichannel_contact", "recordId": cid, "toStatus": "does-not-matter"},
            {},
        )
    db.close()


# ── Nit: reserved-key parity (backend ⊇ frontend), no test pinned it before ─
def test_reserved_field_keys_frontend_is_subset_of_backend():
    """`service_frontend/types/omnichannel.ts RESERVED_CONTACT_FIELD_KEYS` must
    stay a SUBSET of the backend's `RESERVED_FIELD_KEYS` (the backend also
    reserves a few structural wire keys - `id`/`workspaceId`/`customFields` -
    that never appear as a frontend-registrable option). Mirrors the
    `test_branding.py test_frontend_defaults_parity` pattern - pins the two
    lists together so one drifting silently un-reserves a key on one side."""
    import re
    from pathlib import Path

    from modules.omnichannel.services.contact_field_service import RESERVED_FIELD_KEYS

    ts_path = (
        Path(__file__).resolve().parents[2]
        / "service_frontend" / "types" / "omnichannel.ts"
    )
    src = ts_path.read_text()
    block = re.search(
        r"RESERVED_CONTACT_FIELD_KEYS:\s*readonly string\[\]\s*=\s*\[(.*?)\];", src, re.DOTALL
    ).group(1)
    frontend_keys = set(re.findall(r"'([a-zA-Z0-9]+)'", block))
    assert frontend_keys, "parsed zero frontend reserved keys - regex drifted from the TS source"
    assert frontend_keys <= RESERVED_FIELD_KEYS
