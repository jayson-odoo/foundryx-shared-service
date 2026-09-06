"""Omnichannel Contacts module - plan 26 S3 (CSV import + CSV export job with
an authed download route). Covers AC-CTM-34..42.
"""
import csv
import io
import json

from app.import_engine.registry import get_importer
from app.jobs.registry import handler_for
from app.models.background_job import JOB_ABORTED, JOB_DONE, BackgroundJob
from app.models.tenant import DEFAULT_TENANT_ID
from app.workflow_engine.entities import get_workflow_entity
from tests.test_omnichannel_contacts_module import (
    _auth,
    _base,
    _lifecycle_ids,
    _no_perm_auth,
    _other_tenant_auth,
    _seed_contact,
    _tag_id,
    _workspace_id,
)

ENTITY_TYPE = "omnichannel_contacts"


# ── shared helpers ───────────────────────────────────────────────────────────


def _csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _upload(client, h, content, ws_id, *, mode="create_only", **extra):
    data = {
        "entityType": ENTITY_TYPE,
        "mode": mode,
        "context": json.dumps({"workspaceId": ws_id}),
    }
    data.update(extra)
    return client.post(
        "/imports", data=data,
        files={"file": ("contacts.csv", content, "text/csv")},
        headers=h,
    )


def _map(client, h, job_id, mapping, *, ws_id=None):
    body = {"mapping": mapping}
    if ws_id:
        body["context"] = {"workspaceId": ws_id}
    return client.put(f"/imports/{job_id}/mapping", json=body, headers=h)


def _ident(headers_list):
    return {h: h for h in headers_list}


def _commit(client, h, job_id, **opts):
    return client.post(f"/imports/{job_id}/commit", json=opts or None, headers=h)


# ── AC-CTM-34: registration + module gate ───────────────────────────────────


def test_importer_registered_with_module_perm_context():
    importer = get_importer(ENTITY_TYPE)
    assert importer is not None
    assert importer.module == "omnichannel"
    assert importer.write_permission == "contacts.import"
    assert importer.context_keys == ("workspaceId",)
    assert importer.workflow_entity_type == "omnichannel_contact"


def test_importer_hidden_for_tenant_without_module(client, session_factory):
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="No Omni", slug="no-omni-ctm", admin_email="admin@no-omni-ctm.example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.commit()
    db.close()

    res = client.post(
        "/auth/login",
        json={"email": "admin@no-omni-ctm.example.com", "password": "Password123!", "tenantSlug": "no-omni-ctm"},
    )
    h = {"Authorization": f"Bearer {res.json()['access_token']}"}
    res2 = client.post(
        "/imports",
        data={"entityType": ENTITY_TYPE, "mode": "create_only", "context": json.dumps({"workspaceId": "x"})},
        files={"file": ("c.csv", b"phone\n", "text/csv")},
        headers=h,
    )
    assert res2.status_code == 404


# ── AC-CTM-38: drift guard ───────────────────────────────────────────────────


def test_drift_guard_columns_subset_of_writable_plus_documented_exceptions():
    importer = get_importer(ENTITY_TYPE)
    wf = get_workflow_entity("omnichannel_contact")
    exceptions = {"id", "phone", "lifecycle", "tags"}  # import-only identity/relation columns
    for col in importer.columns:
        if col.key in exceptions:
            continue
        assert col.attr in wf.writable, f"{col.key} (attr={col.attr}) not in writable whitelist"

    # Nit 22 (review round 1, AC-CTM-38): the OLD assertion here
    # (`"cf_company".startswith(CF_PREFIX)`) was a tautology - a hardcoded
    # literal string checked against a prefix constant, proving nothing
    # about the ACTUAL dynamic cf_* columns or how they're whitelisted.
    # `custom_fields_json` (the attr every `cf_<key>` column ultimately
    # writes into via `ContactProfileService.patch`) is DELIBERATELY absent
    # from `wf.writable` - documented here, not a silent gap - because
    # custom fields ride their OWN per-key whitelist
    # (`ContactFieldService`'s registered-field-type registry).
    assert "custom_fields_json" not in wf.writable


def test_drift_guard_cf_columns_use_the_field_registrys_own_type(client, session_factory):
    """The REAL "whitelist property" for `cf_<key>` columns (AC-CTM-38, tying
    into finding 12): a dynamic column's TYPE/OPTIONS come from the field's
    OWN registration, so an out-of-whitelist value 422s naming the allowed
    set - proving the per-key registry (not `wf.writable`, which doesn't
    cover custom fields at all) is the real gate. `_dynamic_cf_columns`
    NEVER offers a column for a key that isn't currently registered (a
    deleted/renamed field simply drops out of `effective_columns`), so an
    "unregistered key" cell can't even enter a prepared row through the
    normal upload+map flow - the registry IS the whitelist."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(
        f"{_base(ws)}/contact-fields", headers=h,
        json={"key": "tier", "label": "Tier", "type": "list", "options": ["Bronze", "Gold"]},
    )

    content = _csv_bytes([["phone", "cf_tier"], ["+60 19-000 0001", "Platinum"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, {"phone": "phone", "cf_tier": "cf_tier"})
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    err = next(e for e in job["errors"] if e["column"] == "cf_tier")
    assert "Bronze" in err["message"] and "Gold" in err["message"]


def test_import_columns_match_documented_set():
    importer = get_importer(ENTITY_TYPE)
    keys = {c.key for c in importer.columns}
    assert keys == {
        "id", "phone", "firstName", "lastName", "email", "language",
        "countryCode", "priority", "lifecycle", "tags",
    }


def test_dynamic_cf_columns_derive_type_from_the_field_registry(client, session_factory):
    """Finding 12 (review round 1): a `cf_*` column's `ImportColumn.type` is
    no longer a blanket `"string"` - `list` -> `enum` (options = the field's
    OWN registered options, so a bad value 422s naming the allowed set) and
    `checkbox` -> `boolean`; `date`/`email`/`url`/`text` stay `string`
    (documented, not silently worked around)."""
    from app.import_engine.registry import get_importer

    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(
        f"{_base(ws)}/contact-fields", headers=h,
        json={"key": "plan", "label": "Plan", "type": "list", "options": ["Free", "Pro"]},
    )
    client.post(
        f"{_base(ws)}/contact-fields", headers=h,
        json={"key": "vip", "label": "VIP", "type": "checkbox"},
    )

    importer = get_importer(ENTITY_TYPE)
    db = session_factory()
    dynamic = {
        c.key: c for c in importer.effective_columns(db, DEFAULT_TENANT_ID, {"workspaceId": ws})
    }
    db.close()
    assert dynamic["cf_plan"].type == "enum"
    assert dynamic["cf_plan"].options == ["Free", "Pro"]
    assert dynamic["cf_vip"].type == "boolean"

    # A value outside the registered options 422s naming the allowed set -
    # NOT a generic "Unknown custom field"/format error.
    content = _csv_bytes([["phone", "cf_plan"], ["+60 18-000 0001", "Enterprise"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, {"phone": "phone", "cf_plan": "cf_plan"})
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    err = next(e for e in job["errors"] if e["column"] == "cf_plan")
    assert "Free" in err["message"] and "Pro" in err["message"]

    # A valid option round-trips to the SAME canonical string the field
    # stores (case-insensitive match -> canonical value).
    content2 = _csv_bytes([["phone", "cf_plan", "cf_vip"], ["+60 18-000 0002", "pro", "yes"]])
    job_id2 = _upload(client, h, content2, ws).json()["jobId"]
    _map(client, h, job_id2, {"phone": "phone", "cf_plan": "cf_plan", "cf_vip": "cf_vip"})
    assert _commit(client, h, job_id2).status_code == 200
    data = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    row = next(c for c in data if c["phone"] == "+60180000002")
    assert row["customFields"] == {"plan": "Pro", "vip": True}


# ── AC-CTM-35/36: Test phase errors, zero writes ────────────────────────────


def test_validate_missing_required_phone_on_create(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    content = _csv_bytes([["phone", "firstName"], ["", "NoPhone"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "firstName"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["status"] == "validated"
    assert job["invalidRows"] == 1
    assert any(e["column"] == "phone" for e in job["errors"])


def test_validate_id_rules_per_mode(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    existing = _seed_contact(session_factory, ws, first="Existing", phone="+60 12-000 0001")

    # id present in create-only mode.
    content = _csv_bytes([["id", "phone"], [existing, "+60 12-000 0002"]])
    job_id = _upload(client, h, content, ws, mode="create_only").json()["jobId"]
    _map(client, h, job_id, _ident(["id", "phone"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    assert any(e["column"] == "id" for e in job["errors"])

    # id absent in update-only mode.
    content2 = _csv_bytes([["id", "phone"], ["", "+60 12-000 0003"]])
    job_id2 = _upload(client, h, content2, ws, mode="update_only").json()["jobId"]
    _map(client, h, job_id2, _ident(["id", "phone"]))
    job2 = client.get(f"/imports/{job_id2}", headers=h).json()
    assert job2["invalidRows"] == 1
    assert any(e["column"] == "id" for e in job2["errors"])


def test_validate_duplicate_phone_in_file_and_table(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="Present", phone="+60 13-111 1111")

    content = _csv_bytes(
        [
            ["phone", "firstName"],
            ["+60 14-222 2222", "A"],
            ["+60 14-222 2222", "B"],  # dup within file
            ["+60 13-111 1111", "C"],  # dup vs table
        ]
    )
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "firstName"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 2
    cols = {e["column"] for e in job["errors"]}
    assert cols == {"phone"}
    before = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]
    assert before == 1  # Test phase wrote NOTHING


def test_validate_duplicate_phone_against_unstamped_legacy_row(client, session_factory):
    """Finding 6: a row inserted before `phone_digits` was stamped (or a
    pre-existing fixture) has `phone_digits IS NULL` - the Test-phase
    uniqueness check must still catch a duplicate against it (mirrors
    `ContactRepository.find_by_phone_digits`'s own legacy fallback), so
    manual create/import agree on what counts as a duplicate."""
    from modules.omnichannel.models import Contact

    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    legacy = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws,
        first_name="Legacy", phone="+60 16-333 4444", phone_digits=None,
    )
    db.add(legacy)
    db.commit()
    db.close()

    content = _csv_bytes([["phone", "firstName"], ["+60 16-333 4444", "New"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "firstName"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    assert job["errors"][0]["column"] == "phone"


def test_validate_rejects_foreign_tenant_workspace_context(client, session_factory):
    """Finding 5: `context.workspaceId` is caller-authored and must be
    tenant-scoped before ANY row validates/writes - a job authored by tenant
    A but pointed at tenant B's workspace id must aggregate-fail, never
    validate/commit into it."""
    from tests.test_omnichannel_contacts_module import _other_tenant_auth

    h = _auth(client)
    h_other = _other_tenant_auth(client, session_factory, slug="other-ctm-import-ctx")
    foreign_ws = _workspace_id(client, h_other)

    content = _csv_bytes([["phone", "firstName"], ["+60 17-000 0001", "Foreign"]])
    job_id = _upload(client, h, content, foreign_ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "firstName"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    assert job["errors"][0]["column"] == "workspaceId"

    commit_res = _commit(client, h, job_id)
    assert commit_res.status_code == 200
    assert not commit_res.json().get("createdIds")


def test_validate_unknown_lifecycle_stage(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    content = _csv_bytes([["phone", "lifecycle"], ["+60 15-000 0001", "not-a-real-stage"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "lifecycle"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    assert any(e["column"] == "lifecycle" for e in job["errors"])


def test_validate_custom_field_type_error(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={"key": "budget", "label": "Budget", "type": "number"})
    content = _csv_bytes([["phone", "cf_budget"], ["+60 16-000 0001", "not-a-number"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, {"phone": "phone", "cf_budget": "cf_budget"})
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1
    assert any(e["column"] == "cf_budget" for e in job["errors"])


# ── AC-CTM-37: Import phase (all-or-nothing, defaults, phone immutability) ──


def test_commit_creates_contacts_with_defaults_tags_and_custom_fields(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    lifecycle = _lifecycle_ids(session_factory, ws)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={"key": "budget", "label": "Budget", "type": "number"})

    content = _csv_bytes(
        [
            ["phone", "firstName", "lastName", "tags", "cf_budget"],
            ["+60 17-000 0001", "Nadia", "Khan", "VIP,Cold", "150"],
            ["+60 17-000 0002", "Sam", "Lee", "", ""],
        ]
    )
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, {"phone": "phone", "firstName": "firstName", "lastName": "lastName", "tags": "tags", "cf_budget": "cf_budget"})
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["status"] == "validated" and job["invalidRows"] == 0

    res = _commit(client, h, job_id)
    assert res.status_code == 200
    done = client.get(f"/imports/{job_id}", headers=h).json()
    assert done["status"] == "done"
    assert len(done["createdIds"]) == 2

    data = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    nadia = next(c for c in data if c["firstName"] == "Nadia")
    assert nadia["phone"] == "+60170000001"
    assert nadia["lifecycle"]["statusId"] == lifecycle["new_lead"]  # default initial stage
    assert nadia["customFields"] == {"budget": 150.0}
    assert {t["name"] for t in nadia["tags"]} == {"VIP", "Cold"}

    from modules.omnichannel.models import Contact

    db = session_factory()
    row = db.query(Contact).filter(Contact.id == nadia["id"]).first()
    assert row.phone_digits == "60170000001"
    db.close()


def test_commit_explicit_lifecycle_stage(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    lifecycle = _lifecycle_ids(session_factory, ws)
    content = _csv_bytes([["phone", "lifecycle"], ["+60 18-000 0001", "hot_lead"]])
    job_id = _upload(client, h, content, ws).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "lifecycle"]))
    _commit(client, h, job_id)
    data = client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]
    row = next(c for c in data if c["phone"] == "+60180000001")
    assert row["lifecycle"]["statusId"] == lifecycle["hot_lead"]


def test_commit_all_or_nothing_on_mid_file_failure(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    before = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]

    content = _csv_bytes(
        [
            ["phone", "lifecycle"],
            ["+60 19-000 0001", ""],
            ["+60 19-000 0002", "not-a-real-stage"],  # invalid
        ]
    )
    job_id = _upload(client, h, content, ws, abortOnInvalid=True).json()["jobId"]
    _map(client, h, job_id, _ident(["phone", "lifecycle"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 1

    res = _commit(client, h, job_id, triggerAutomations=False)
    assert res.status_code == 200
    done = client.get(f"/imports/{job_id}", headers=h).json()
    assert done["status"] == "failed"

    after = client.get(f"{_base(ws)}/contacts", headers=h).json()["total"]
    assert after == before  # NOTHING committed, even the valid row


def test_commit_update_id_match_never_touches_phone(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_contact(session_factory, ws, first="Old", phone="+60 20-000 0001")

    content = _csv_bytes([["id", "phone", "firstName"], [cid, "+60 20-999 9999", "New"]])
    job_id = _upload(client, h, content, ws, mode="update_only").json()["jobId"]
    _map(client, h, job_id, _ident(["id", "phone", "firstName"]))
    job = client.get(f"/imports/{job_id}", headers=h).json()
    assert job["invalidRows"] == 0
    res = _commit(client, h, job_id)
    assert res.status_code == 200

    from modules.omnichannel.models import Contact

    db = session_factory()
    row = db.query(Contact).filter(Contact.id == cid).first()
    assert row.phone == "+60 20-000 0001"  # UNCHANGED
    assert row.first_name == "New"
    db.close()


def test_commit_cross_workspace_id_is_not_updated(client, session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    h = _auth(client)
    ws = _workspace_id(client, h)

    db = session_factory()
    other_ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Second WS",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()
    foreign_id = _seed_contact(session_factory, other_ws_id, first="Foreign", phone="+60 21-000 0001")

    content = _csv_bytes([["id", "firstName"], [foreign_id, "Hijacked"]])
    job_id = _upload(client, h, content, ws, mode="update_only").json()["jobId"]
    _map(client, h, job_id, _ident(["id", "firstName"]))
    _commit(client, h, job_id)

    from modules.omnichannel.models import Contact

    db2 = session_factory()
    row = db2.query(Contact).filter(Contact.id == foreign_id).first()
    assert row.first_name == "Foreign"  # untouched - never cross-workspace-written
    db2.close()


def test_trigger_automations_gate(client, session_factory, monkeypatch):
    from app.workflow_engine import entity_events

    seen = []
    monkeypatch.setattr(
        entity_events, "emit_entity_event",
        lambda db, entity_type, action, record, **kw: seen.append((entity_type, action)),
    )
    h = _auth(client)
    ws = _workspace_id(client, h)

    content_off = _csv_bytes([["phone"], ["+60 22-000 0001"]])
    job_off = _upload(client, h, content_off, ws).json()["jobId"]
    _map(client, h, job_off, _ident(["phone"]))
    _commit(client, h, job_off, triggerAutomations=False)
    assert seen == []

    content_on = _csv_bytes([["phone"], ["+60 22-000 0002"]])
    job_on = _upload(client, h, content_on, ws).json()["jobId"]
    _map(client, h, job_on, _ident(["phone"]))
    _commit(client, h, job_on, triggerAutomations=True)
    assert ("omnichannel_contact", "created") in seen


def test_import_permission_gate_403(client, session_factory):
    h_none = _no_perm_auth(client, session_factory, email="ctm-import-noperm@example.com")
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(
        "/imports",
        data={"entityType": ENTITY_TYPE, "mode": "create_only", "context": json.dumps({"workspaceId": ws})},
        files={"file": ("c.csv", b"phone\n+60 23-000 0001\n", "text/csv")},
        headers=h_none,
    )
    assert res.status_code == 403


# ── AC-CTM-39..42: export job + authed download ─────────────────────────────


def test_export_creates_job_writes_csv_and_downloads(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="Ann", last="Lee", phone="+60 24-000 0001", email="ann@example.com")
    handler_for("omnichannel.contacts_export")  # loud if unregistered

    res = client.post(
        f"{_base(ws)}/contacts/export", headers=h,
        json={"columns": ["name", "phone", "email"]},
    )
    assert res.status_code == 201
    job_id = res.json()["jobId"]

    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["status"] == "done"
    assert job["result"]["rowCount"] == 1
    assert job["result"]["columns"][0] == "id"  # id ALWAYS first (AC-CTM-42)

    download = client.get(f"{_base(ws)}/contacts/export/{job_id}/file", headers=h)
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "private, max-age=0, no-store"
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["ID", "Name", "Phone", "Email"]
    assert rows[1][0] == a
    assert rows[1][1] == "Ann Lee"


def test_export_honours_ids_selection_over_filter(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    a = _seed_contact(session_factory, ws, first="Keep")
    _seed_contact(session_factory, ws, first="Skip")

    res = client.post(
        f"{_base(ws)}/contacts/export", headers=h,
        json={"columns": ["name"], "ids": [a], "search": "Skip"},  # ids must WIN over search
    )
    job_id = res.json()["jobId"]
    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["result"]["rowCount"] == 1

    download = client.get(f"{_base(ws)}/contacts/export/{job_id}/file", headers=h)
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2  # header + the one selected row
    assert rows[1][0] == a


def test_export_columns_reject_unknown_id_and_cap(client, session_factory):
    """Finding 14: an unknown column id 422s at the wire (never a silent
    blank cell from `_column_value`'s catch-all), and the column LIST is
    capped."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="A")

    res = client.post(
        f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name", "notAColumn"]}
    )
    assert res.status_code == 422

    res2 = client.post(f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name"] * 51})
    assert res2.status_code == 422

    # A well-FORMED but UNREGISTERED customFields.<key> also 422s (registered-
    # key check, DB + workspace scoped - lives in `create_export_job`).
    res3 = client.post(
        f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name", "customFields.notRegistered"]}
    )
    assert res3.status_code == 422

    # A REGISTERED customFields.<key> is accepted.
    client.post(
        f"{_base(ws)}/contact-fields", headers=h, json={"key": "budget", "label": "Budget", "type": "number"}
    )
    res4 = client.post(
        f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name", "customFields.budget"]}
    )
    assert res4.status_code == 201


def test_export_row_cap_422(client, session_factory, monkeypatch):
    from modules.omnichannel.services import contact_export_service as svc

    monkeypatch.setattr(svc, "EXPORT_MAX_ROWS", 1)
    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="A")
    _seed_contact(session_factory, ws, first="B")

    res = client.post(f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name"]})
    assert res.status_code == 422


def test_export_download_uniform_404_before_done_and_wrong_tenant(client, session_factory):
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="A")
    res = client.post(f"{_base(ws)}/contacts/export", headers=h, json={"columns": ["name"]})
    job_id = res.json()["jobId"]

    # A bogus job id, and another tenant's attempt - both uniform 404.
    assert client.get(f"{_base(ws)}/contacts/export/not-a-job/file", headers=h).status_code == 404

    h2 = _other_tenant_auth(client, session_factory, slug="other-ctm-export")
    ws2 = _workspace_id(client, h2)
    assert client.get(f"{_base(ws2)}/contacts/export/{job_id}/file", headers=h2).status_code == 404

    # A DIFFERENT workspace of the SAME tenant (nit 22) - the job is
    # workspace-scoped, not just tenant-scoped.
    db = session_factory()
    other_ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Export Second WS",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()
    assert (
        client.get(f"{_base(other_ws_id)}/contacts/export/{job_id}/file", headers=h).status_code
        == 404
    )


def test_export_cooperative_cancel_stops_before_file(client, session_factory):
    from modules.omnichannel.services.contact_export_service import run_contacts_export

    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="A")
    _seed_contact(session_factory, ws, first="B")

    db = session_factory()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="omnichannel.contacts_export", status=JOB_ABORTED,
        payload_json={"workspaceId": ws, "columns": ["id", "name"]},
    )
    db.add(job)
    db.commit()
    job_id = job.id

    run_contacts_export(db, job)
    db.refresh(job)
    assert job.status == JOB_ABORTED  # never overwritten to DONE
    assert not (job.result_json or {}).get("fileKey")
    db.close()

    h_admin = _auth(client)
    assert client.get(f"{_base(ws)}/contacts/export/{job_id}/file", headers=h_admin).status_code == 404


def test_export_permission_gate_403(client, session_factory):
    h_none = _no_perm_auth(client, session_factory, email="ctm-export-noperm@example.com")
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contacts/export", headers=h_none, json={"columns": ["name"]})
    assert res.status_code == 403


# ── Review round 1, Blocker 1 + promoted tags delimiter: CSV formula-
# injection sanitize + an ACTUAL re-import round-trip (AC-CTM-42) ───────────


def test_export_sanitizes_formula_cells_and_round_trips_via_reimport(client, session_factory):
    """`firstName`/`lastName` come from inbound WhatsApp `profile_name` -
    attacker-controlled free text. A cell that starts with `= + - @` must be
    written prefixed with `'` (Excel/Sheets formula-injection guard); `phone`
    always starts with `+` so it ALWAYS gets the guard too - re-importing the
    exact downloaded file must still resolve to the SAME digits
    (`_normalize_phone` strips non-digit characters, quote included). Tags
    export/import on the SAME `,` delimiter (promoted finding) - the full
    tag set must survive the round-trip."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_contact(
        session_factory, ws, first="=2+5(evil)", last="+SUM(A1:A9)",
        phone="+60 24-555 0001", tag_names=["VIP", "Ops"],
    )

    res = client.post(
        f"{_base(ws)}/contacts/export", headers=h,
        json={"columns": ["id", "firstName", "lastName", "phone", "tags"]},
    )
    job_id = res.json()["jobId"]
    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["status"] == "done"

    download = client.get(f"{_base(ws)}/contacts/export/{job_id}/file", headers=h)
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header, row = rows[0], rows[1]
    assert header == ["ID", "First name", "Last name", "Phone", "Tags"]
    assert row[0] == cid
    assert row[1] == "'=2+5(evil)"  # sanitized - literal text, never a formula
    assert row[2] == "'+SUM(A1:A9)"
    assert row[3].startswith("'+")  # every phone starts with `+` - always guarded
    tag_set = set(row[4].split(","))
    assert tag_set == {"VIP", "Ops"}

    # Re-import the EXACT downloaded file - `phone` is deliberately NEVER
    # rewritten by an update_only row (AC-CTM-37 - see `_update_contacts`), so
    # the phone-normalization round-trip is exercised the way it actually
    # happens in the wild: a CREATE row from a re-uploaded export (`id`
    # present in the file but left UNMAPPED - never mapped to the system `id`
    # column - so create_only sees no id and makes a NEW contact) into a
    # SECOND workspace (the ORIGINAL workspace already holds this exact
    # phone, and the duplicate-phone table check would otherwise reject the
    # row - itself proof the normalization round-trips identically, asserted
    # separately below).
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses as omni_statuses

    db_ws = session_factory()
    ws2 = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Reimport WS",
        status_id=omni_statuses.status_id_for(db_ws, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db_ws.add(ws2)
    db_ws.commit()
    ws2_id = ws2.id
    db_ws.close()

    job_id_dup = _upload(client, h, download.content, ws, mode="create_only").json()["jobId"]
    _map(
        client, h, job_id_dup,
        {"First name": "firstName", "Last name": "lastName", "Phone": "phone", "Tags": "tags"},
    )
    dup_job = client.get(f"/imports/{job_id_dup}", headers=h).json()
    assert dup_job["invalidRows"] == 1  # SAME digits as the seeded contact -> dup rejected
    assert dup_job["errors"][0]["column"] == "phone"

    job_id2 = _upload(client, h, download.content, ws2_id, mode="create_only").json()["jobId"]
    _map(
        client, h, job_id2,
        {"First name": "firstName", "Last name": "lastName", "Phone": "phone", "Tags": "tags"},
    )
    commit_res = _commit(client, h, job_id2)
    assert commit_res.status_code == 200
    new_id = commit_res.json()["createdIds"][0]
    assert new_id != cid

    from modules.omnichannel.models import Contact, ContactTag, ContactTagLink

    db = session_factory()
    row_db = db.query(Contact).filter(Contact.id == new_id).first()
    # `_normalize_phone` -> digits_only strips the leading `'` (AND the `+`,
    # AND the spaces/dashes) then re-prepends `+` - the round-trip restores
    # the SAME number the ORIGINAL contact was seeded with.
    assert row_db.phone == "+60245550001"
    assert row_db.phone_digits == "60245550001"
    tag_names = {
        t.name
        for t in db.query(ContactTag)
        .join(ContactTagLink, ContactTagLink.tag_id == ContactTag.id)
        .filter(ContactTagLink.contact_id == new_id)
        .all()
    }
    assert tag_names == {"VIP", "Ops"}  # the full tag set survives the round-trip
    db.close()
