"""Plan 33 (roadmap A6), slice S5 - CSV fallback + failure export
(AC-MIG-46..49, plus the cross-cutting AC-MIG-50..53 as they apply to the new
upload + failure-export routes).

Reuses S2's fixtures (`_default_workspace`, `_auth`, `_row_counts`) - the
established cross-test-helper-import pattern this suite already uses.
"""
import base64
import codecs
import csv
import io
from typing import Dict, List, Optional

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import Contact, MigrationRef
from modules.omnichannel.repositories.migration_upload_repository import MigrationUploadRepository
from modules.omnichannel.services.migration_service import (
    MIGRATION_JOB_TYPE,
    MigrationService,
    run_migration_job,
)

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _default_workspace,
    _default_workspace_id,
    _row_counts,
)


def _upload_key(db, tenant_id: str, kind: str, content: bytes) -> str:
    """Review round 1, finding B2 renamed `upload_csv`'s return from the raw
    storage key to an opaque receipt `id` (`MigrationUploadResult.id`).
    These are DIRECT handler-level tests (`run_migration_job` against a
    hand-built `BackgroundJob.payload_json`, bypassing `create_job`'s own
    id-to-key resolution) - they still need the underlying storage key,
    fetched straight off the persisted `MigrationUpload` receipt row."""
    result = MigrationService(db).upload_csv(tenant_id, kind, content)
    return MigrationUploadRepository(db).get_for_tenant(tenant_id, result.id).storage_key


# A REAL 1x1 transparent PNG (actual zlib-compressed IDAT bytes) - unlike a
# hand-typed ASCII-ish "fake png", this is NOT decodable as text by
# `charset_normalizer`, so `app/import_engine/readers.py sniff_format`
# genuinely rejects it (verified: a naive concatenated-ASCII "fake PNG" is
# mis-sniffed as csv, since arbitrary printable bytes usually DO decode as
# some charset - only real binary compressed data reliably fails).
_REAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _csv_bytes(headers: List[str], rows: List[List[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _make_csv_job(
    db,
    tenant_id,
    *,
    workspace_id: str,
    contacts_csv_key: str,
    mode: str = "run",
    header_map: Optional[Dict[str, str]] = None,
    snippets_csv_key: Optional[str] = None,
    contacts_only: bool = False,
    connection_id: Optional[str] = None,
):
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    job = BackgroundJob(
        tenant_id=tenant_id, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={
            "mode": mode, "source": "csv", "connectionId": connection_id, "workspaceId": workspace_id,
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsOnly": contacts_only, "mappingHash": "test-csv",
            "contactsCsvKey": contacts_csv_key, "csvHeaderMap": header_map or {},
            "snippetsCsvKey": snippets_csv_key,
        },
    )
    db.add(job)
    db.commit()
    return job


# ═══════════════════════════════════════════════════════════════════════════
# Upload route (AC-MIG-46/47) - sniff, size cap, permission
# ═══════════════════════════════════════════════════════════════════════════


def test_upload_csv_returns_key_row_count_and_headers(client):
    h = _auth(client)
    content = _csv_bytes(["First Name", "Phone"], [["Ada", "+15550001"], ["Bob", "+15550002"]])
    res = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["rowCount"] == 2
    assert body["headers"] == ["First Name", "Phone"]
    assert body["id"]


def test_upload_rejects_a_png_named_csv(client):
    h = _auth(client)
    res = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", _REAL_PNG_BYTES, "text/csv")}, data={"kind": "contacts"},
    )
    assert res.status_code == 422, res.text


def test_upload_rejects_oversize_file(client, monkeypatch):
    import modules.omnichannel.routers.migration as migration_router

    monkeypatch.setattr(migration_router, "MIGRATION_UPLOAD_MAX_BYTES", 10)
    h = _auth(client)
    content = _csv_bytes(["First Name"], [["A" * 50]])
    res = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert res.status_code == 413


def test_upload_requires_manage_permission(client, session_factory):
    from app.models import Permission, Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    read_perm = db.query(Permission).filter(Permission.key == "omnichannel_migration.read").first()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Migration Reader S5")
    role.permissions = [read_perm]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email="reader-s5@example.com",
        password=hash_password("Password123!"), name="ReaderS5", status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    h = _auth(client, email="reader-s5@example.com", password="Password123!")
    content = _csv_bytes(["First Name"], [["A"]])
    res = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert res.status_code == 403


def test_upload_kind_must_be_contacts_or_snippets(client):
    h = _auth(client)
    content = _csv_bytes(["First Name"], [["A"]])
    res = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("x.csv", content, "text/csv")}, data={"kind": "bogus"},
    )
    assert res.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Job create validation (AC-MIG-47)
# ═══════════════════════════════════════════════════════════════════════════


def test_create_csv_job_requires_contacts_csv_key_422(client):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    res = client.post(
        "/omnichannel/migration/jobs", headers=h,
        json={
            "workspaceId": ws_id, "mode": "dry_run", "source": "csv",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
        },
    )
    assert res.status_code == 422, res.text
    assert "contactsUploadId" in res.json()["detail"]["fieldErrors"]


def test_create_csv_job_without_a_connection_succeeds(client):
    """D-A6-25 - `connectionId` is optional in CSV mode (a customer with no
    API access may never have a respond.io connection row at all)."""
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    content = _csv_bytes(["First Name", "Phone"], [["Csv", "+15559990001"]])
    up = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert up.status_code == 201, up.text
    upload_id = up.json()["id"]

    res = client.post(
        "/omnichannel/migration/jobs", headers=h,
        json={
            "workspaceId": ws_id, "mode": "dry_run", "source": "csv",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsUploadId": upload_id,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["connectionId"] == ""
    assert res.json()["status"] == "done"


# ═══════════════════════════════════════════════════════════════════════════
# Direct handler tests (AC-MIG-47/48/49) - `run_migration_job` against a
# hand-built CSV-mode job row.
# ═══════════════════════════════════════════════════════════════════════════


def test_header_map_with_operator_choice_and_aliases(session_factory):
    """Explicit `csvHeaderMap` wins; unmapped keys fall back to a
    case-insensitive alias guess (plan §5.6's own column names)."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)

    content = _csv_bytes(
        ["Given Name", "last name", "Mobile", "Email", "Country"],
        [["Alias", "Guessed", "+15551230001", "alias@example.com", "my"]],
    )
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    job = _make_csv_job(
        db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key,
        header_map={"firstName": "Given Name", "phone": "Mobile"},  # operator maps these two
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.workspace_id == ws.id).first()
    assert contact.first_name == "Alias"          # operator-mapped
    assert contact.phone == "+15551230001"        # operator-mapped
    assert contact.last_name == "Guessed"         # alias-guessed ("last name")
    assert contact.email == "alias@example.com"   # alias-guessed ("Email")
    assert contact.country_code == "MY"           # alias-guessed ("Country"), upper-cased
    db.close()


def test_unmapped_header_reported_never_silently_dropped(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    content = _csv_bytes(
        ["First Name", "Phone", "Notes"],
        [["Noted", "+15551230099", "some internal note"]],
    )
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    blockers = job.result_json["report"]["blockers"]
    assert any("Notes" in b for b in blockers), blockers
    db.close()


def test_bom_and_delimiter_sniffed_like_the_rest_of_the_engine(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    raw = codecs.BOM_UTF8 + _csv_bytes(["First Name", "Phone"], [["Bommed", "+15551230077"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", raw)
    db.commit()

    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key)
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    contact = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15551230077"
    ).first()
    assert contact is not None
    assert contact.first_name == "Bommed"
    db.close()


def test_dry_run_writes_nothing_csv_mode_paired_with_real_mode_control(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    content = _csv_bytes(["First Name", "Phone"], [["Dry", "+15559990011"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    before = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    dry_job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="dry_run")
    run_migration_job(db, dry_job)
    after_dry = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after_dry == before, "a CSV-mode dry run must write zero rows anywhere too"
    assert dry_job.result_json["report"]["entities"]["contacts"]["wouldCreate"] == 1

    real_job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, real_job)
    after_real = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after_real["contacts"] == before["contacts"] + 1
    assert after_real["refs"] == before["refs"] + 1
    db.close()


def test_csv_rerun_via_migration_refs_creates_no_duplicates_with_explicit_id(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    content = _csv_bytes(
        ["Contact ID", "First Name", "Phone"], [["rio-9001", "Once", "+15559990033"]]
    )
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    before = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    job1 = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job1)
    after1 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after1["contacts"] == before["contacts"] + 1
    assert after1["refs"] == before["refs"] + 1
    ref = db.query(MigrationRef).filter(
        MigrationRef.tenant_id == DEFAULT_TENANT_ID, MigrationRef.entity_type == "contact",
        MigrationRef.external_id == "rio-9001",
    ).first()
    assert ref is not None, "an explicit Contact ID column is used as the migration_refs external id"

    job2 = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job2)
    after2 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after2["contacts"] == after1["contacts"], "a re-run must create no duplicate contact"
    assert after2["refs"] == after1["refs"]
    assert job2.result_json["report"]["entities"]["contacts"]["wouldUpdate"] == 1
    db.close()


def test_csv_rerun_creates_no_duplicates_via_stable_row_hash_when_id_absent(session_factory):
    """D-A6-25 - no "Contact ID" column mapped -> a deterministic hash of the
    row's mapped values is the migration_refs external id, so re-running the
    identical file is still idempotent."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    content = _csv_bytes(["First Name", "Phone"], [["Hashed", "+15559990044"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    before = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    job1 = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job1)
    after1 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after1["contacts"] == before["contacts"] + 1

    job2 = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job2)
    after2 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after2["contacts"] == after1["contacts"]
    assert after2["refs"] == after1["refs"]
    db.close()


def test_csv_mode_blockers_media_identity_messages_stated_up_front(session_factory):
    """AC-MIG-48 - stated in EVERY CSV-mode report (dry run included), never
    discovered mid-run."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    content = _csv_bytes(["First Name", "Phone"], [["Blocked", "+15559990055"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    db.commit()

    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)
    blockers = " ".join(job.result_json["report"]["blockers"])
    assert "message history is not migrated" in blockers
    assert "no channel identity" in blockers
    assert "no media" in blockers
    # No identities/messages/media/events phase ever ran (structural, AC-MIG-48).
    entities = job.result_json["report"]["entities"]
    for key_ in ("identities", "messages", "media", "events"):
        assert entities[key_]["fetched"] == 0
    db.close()


def test_csv_contacts_row_cap_boundary_2499_vs_2500(session_factory, monkeypatch):
    """AC-MIG-49 - the row-cap warning fires AT the boundary, not before.

    Review round 1, finding S13 - the ORIGINAL version of this test wrote
    2500 real contact rows TWICE (~5s) to exercise the real
    `CSV_CONTACTS_ROW_CAP` constant. `_process_csv_contacts` reads the cap
    off the `migration_service` MODULE at call time (a plain global, not a
    bound default), so monkeypatching it down to a small number exercises
    the exact same boundary condition in a fraction of the rows/time."""
    import modules.omnichannel.services.migration_service as migration_service_module

    small_cap = 5
    monkeypatch.setattr(migration_service_module, "CSV_CONTACTS_ROW_CAP", small_cap)

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)

    def _n_row_csv(n: int) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["First Name", "Phone"])
        for i in range(n):
            w.writerow([f"P{i}", f"+1555{i:07d}"])
        return buf.getvalue().encode("utf-8")

    key_under = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _n_row_csv(small_cap - 1))
    db.commit()
    job_under = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key_under, mode="dry_run")
    run_migration_job(db, job_under)
    db.refresh(job_under)
    assert job_under.status == "done", job_under.error
    assert not any("cap" in b.lower() for b in job_under.result_json["report"]["blockers"])

    key_at = _upload_key(db, DEFAULT_TENANT_ID, "contacts", _n_row_csv(small_cap))
    db.commit()
    job_at = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key_at, mode="dry_run")
    run_migration_job(db, job_at)
    db.refresh(job_at)
    assert job_at.status == "done", job_at.error
    assert any(str(small_cap) in b for b in job_at.result_json["report"]["blockers"])
    db.close()


def test_csv_mode_reaches_quick_replies_phase_on_real_run(session_factory):
    """CSV mode still processes an (optional) snippets CSV (D-A6-19) even
    though identities/messages/media/events never run for it."""
    from modules.omnichannel.models import QuickReply

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    contacts_content = _csv_bytes(["First Name", "Phone"], [["Snip", "+15559990066"]])
    contacts_key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", contacts_content)
    snippets_content = _csv_bytes(["shortcut", "body"], [["/hi", "Hello there!"]])
    snippets_key = _upload_key(db, DEFAULT_TENANT_ID, "snippets", snippets_content)
    db.commit()

    job = _make_csv_job(
        db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=contacts_key,
        snippets_csv_key=snippets_key, mode="run",
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    qr = db.query(QuickReply).filter(
        QuickReply.tenant_id == DEFAULT_TENANT_ID, QuickReply.workspace_id == ws.id, QuickReply.shortcut == "/hi"
    ).first()
    assert qr is not None
    assert job.result_json["report"]["entities"]["quickReplies"]["wouldCreate"] == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Failure CSV export (AC-MIG-53, D-A6-23) - storage-backed, formula-guarded,
# tenant-scoped, permission-gated.
# ═══════════════════════════════════════════════════════════════════════════


def test_failure_csv_round_trip_formula_guarded_and_empty_when_no_failures(client, session_factory):
    from app.models.background_job import JOB_DONE, BackgroundJob

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)

    # A job with ZERO failures still gets a header-only file (never a
    # "no file yet" special case for a finished job).
    empty_job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws.id, "mode": "run", "source": "csv"},
    )
    db.add(empty_job)
    db.commit()
    empty_job_id = empty_job.id

    from modules.omnichannel.services.migration_service import _write_failures_csv

    failures = [
        {"entity": "contacts", "sourceId": "1", "sourceLabel": "=SUM(A1:A10)",
         "reason": "bad phone", "action": "skipped"},
    ]
    file_key = _write_failures_csv(db, DEFAULT_TENANT_ID, "manual-job", failures)
    guarded_job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws.id, "mode": "run", "source": "csv"},
        result_json={"report": {}, "failures": {"fileKey": file_key, "rowCount": 1, "sample": failures}},
    )
    db.add(guarded_job)
    db.commit()
    guarded_job_id = guarded_job.id
    db.close()

    h = _auth(client)

    res_empty = client.get(f"/omnichannel/migration/jobs/{empty_job_id}/failures.csv", headers=h)
    assert res_empty.status_code == 200
    assert res_empty.headers["content-type"].startswith("text/csv")
    lines = [ln for ln in res_empty.text.strip().splitlines() if ln]
    assert lines == ["entity,sourceId,sourceLabel,reason,action"]

    res_guarded = client.get(f"/omnichannel/migration/jobs/{guarded_job_id}/failures.csv", headers=h)
    assert res_guarded.status_code == 200
    assert "'=SUM(A1:A10)" in res_guarded.text, res_guarded.text
    assert res_guarded.headers["x-content-type-options"] == "nosniff"
    # Review round 1 nit - the CSP-sandbox + cache headers were set on the
    # route (D-A6-23, a PII-carrying download) but never asserted here.
    assert res_guarded.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert res_guarded.headers["cache-control"] == "private, no-store"


def test_failures_csv_requires_read_permission(client, session_factory):
    from app.models import User, UserStatus
    from app.models.background_job import JOB_DONE, BackgroundJob
    from app.security import hash_password

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws.id, "mode": "run", "source": "csv"},
    )
    db.add(job)
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email="no-migration-perm@example.com",
        password=hash_password("Password123!"), name="NoPerm", status=UserStatus.ACTIVE.value,
    )
    user.roles = []
    db.add(user)
    db.commit()
    job_id = job.id
    db.close()

    h = _auth(client, email="no-migration-perm@example.com", password="Password123!")
    res = client.get(f"/omnichannel/migration/jobs/{job_id}/failures.csv", headers=h)
    assert res.status_code == 403


def test_failures_csv_cross_tenant_404(client, session_factory):
    from app.models.background_job import JOB_DONE, BackgroundJob
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws.id, "mode": "run", "source": "csv"},
    )
    db.add(job)
    db.flush()
    job_id = job.id

    tenant = TenantService(db).provision(
        name="Other Tenant S5", slug="other-rio-s5",
        admin_email="admin-other-rio-s5@example.com", admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()

    h2 = _auth(
        client, email="admin-other-rio-s5@example.com", password="Password123!", tenant_slug="other-rio-s5"
    )
    res = client.get(f"/omnichannel/migration/jobs/{job_id}/failures.csv", headers=h2)
    assert res.status_code == 404
