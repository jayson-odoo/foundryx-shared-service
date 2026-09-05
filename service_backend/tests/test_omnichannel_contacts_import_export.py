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
    # cf_<key> columns are dynamic (per-workspace registry) - assert the naming
    # contract holds for a synthetic one instead of a static column.
    from modules.omnichannel.importers import CF_PREFIX

    assert "cf_company".startswith(CF_PREFIX)


def test_import_columns_match_documented_set():
    importer = get_importer(ENTITY_TYPE)
    keys = {c.key for c in importer.columns}
    assert keys == {
        "id", "phone", "firstName", "lastName", "email", "language",
        "countryCode", "priority", "lifecycle", "tags",
    }


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
