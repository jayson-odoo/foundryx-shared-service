"""Plan 30 (roadmap A9), slice S3 - report export job + authed download +
the core-permission reconciliation (AC-RPT-33..40). Against the SAME shared
fixture S1/S2 use (`tests.omnichannel_report_fixture.seed_report_fixture`).

Permission reconciliation (D-A9-10, amended 2026-09-06, final): the export
routes are gated by the CORE `reports.export` key, exactly like the read
routes are gated by `reports.read` - the module declares NO
`conversation_reports.*` rows. Tests below prove: (a) a role holding
`reports.read` but not `.export` gets 403 on both export routes while the
read routes keep working; (b) the demo tenant Admin already holds both core
keys (the pre-existing `tenant_admin_grant`/`sweep_tenant_admin_grants`
sweep, not a new grant); (c) uninstalling the module touches no permission
row at all, because the module owns none of them.
"""
from __future__ import annotations

import csv
import io

import pytest

from app.jobs.registry import handler_for
from app.models import DEFAULT_TENANT_ID, Permission, Role, User, UserStatus
from app.models.background_job import JOB_ABORTED, JOB_DONE, JOB_PENDING, BackgroundJob
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.omnichannel_report_fixture import seed_report_fixture
from tests.test_omnichannel_contact_data_model import _other_tenant_auth


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _base(ws_id: str) -> str:
    return f"/omnichannel/workspaces/{ws_id}"


def _export(client, h, ws_id, report_key, **body):
    payload = {**FIXTURE_RANGE, "tz": KL, **body}
    return client.post(f"{_base(ws_id)}/reports/{report_key}/export", headers=h, json=payload)


def _download(client, h, ws_id, report_key, job_id):
    return client.get(f"{_base(ws_id)}/reports/{report_key}/export/{job_id}/file", headers=h)


def _role_with_keys(session_factory, keys, *, email: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
    db = session_factory()
    user = User(
        tenant_id=tenant_id, email=email, name="Report Perm Test",
        password=hash_password("pw12345678"), status=UserStatus.ACTIVE.value,
    )
    role = Role(tenant_id=tenant_id, name=f"role-{email}")
    role.permissions = PermissionRepository(db).get_by_keys(keys)
    db.add(role)
    db.flush()
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()


@pytest.fixture
def fixture_ids(session_factory):
    db = session_factory()
    ids = seed_report_fixture(db)
    db.close()
    return ids


FIXTURE_RANGE = {"from": "2026-03-01", "to": "2026-03-07"}
KL = "Asia/Kuala_Lumpur"


# ── AC-RPT-33: export job created ────────────────────────────────────────────
def test_export_creates_job_and_registers_handler(client, fixture_ids):
    handler_for("omnichannel.report_export")  # loud if unregistered
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "conversations")
    assert res.status_code == 201, res.text
    job_id = res.json()["jobId"]

    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["status"] == "done"  # eager dev/test
    assert job["result"]["rowCount"] == 7  # one row per bucket (fixture range = 7 days)


# ── AC-RPT-34/35: bucketed report (no per-record rows) exports one row per
# bucket, reusing the SAME series labels the chart uses ────────────────────
def test_export_conversations_bucketed_rows_and_headers(client, fixture_ids):
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "conversations")
    job_id = res.json()["jobId"]

    download = _download(client, h, fixture_ids.workspace_id, "conversations", job_id)
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "private, max-age=0, no-store"

    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Bucket", "Start", "End", "Opened", "Closed", "Reopened"]
    assert len(rows) == 8  # header + 7 daily buckets
    # AC-RPT-18's known totals: opened [2,2,1,0,1,1,0].
    assert [r[3] for r in rows[1:]] == ["2", "2", "1", "0", "1", "1", "0"]
    # Every timestamp column carries the requested tz's offset, never a raw
    # UTC instant (AC-RPT-35) - Asia/Kuala_Lumpur is UTC+08 all year (no DST).
    assert rows[1][1].endswith("+08:00")
    assert rows[1][2].endswith("+08:00")


# ── AC-RPT-34/35: a per-record report (assignment log) exports the SAME rows
# the read route returns, with the createdAt column tz-rendered ────────────
def test_export_assignments_rows_and_timestamp_offset(client, fixture_ids):
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "assignments")
    job_id = res.json()["jobId"]
    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["result"]["rowCount"] == 3  # AC-RPT-26's fixture total

    download = _download(client, h, fixture_ids.workspace_id, "assignments", job_id)
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "Event ID"
    assert rows[0][1] == "Date"
    assert len(rows) == 4  # header + 3 events
    for r in rows[1:]:
        assert r[1].endswith("+08:00")


# ── AC-RPT-35: every cell (incl. an agent name from inbound WhatsApp free
# text) is formula-injection sanitized ──────────────────────────────────────
def test_export_sanitizes_formula_injection_agent_name(client, session_factory, fixture_ids):
    db = session_factory()
    ann_id = fixture_ids.users["ann"]
    db.query(User).filter(User.id == ann_id).update({"name": "=SUM(1,2)"})
    db.commit()
    db.close()

    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "assignments")
    job_id = res.json()["jobId"]
    download = _download(client, h, fixture_ids.workspace_id, "assignments", job_id)
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    flat_cells = [c for row in rows for c in row]
    # `sanitize_cell` prefixes a formula-leading value with `'` - every cell
    # carrying the dangerous name is the PREFIXED form, never the raw one.
    assert "=SUM(1,2)" not in flat_cells
    assert "'=SUM(1,2)" in flat_cells


# ── AC-RPT-35/33: pagination through the assignment log inside the job ──────
def test_export_paginates_through_multiple_pages(client, session_factory, fixture_ids, monkeypatch):
    from modules.omnichannel.services import report_export_service as svc

    monkeypatch.setattr(svc, "EXPORT_PAGE_SIZE", 1)
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "assignments")
    job_id = res.json()["jobId"]
    job = client.get(f"/jobs/{job_id}", headers=h).json()
    assert job["status"] == "done"
    assert job["result"]["rowCount"] == 3  # all 3 rows still delivered across 3 pages of 1

    download = _download(client, h, fixture_ids.workspace_id, "assignments", job_id)
    rows = list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))
    assert len(rows) == 4  # header + 3 rows, none dropped/duplicated across pages


# ── AC-RPT-36: row cap fails fast, before any job row exists ────────────────
def test_export_row_cap_422(client, fixture_ids, monkeypatch):
    from modules.omnichannel.services import report_export_service as svc

    monkeypatch.setattr(svc, "EXPORT_MAX_ROWS", 1)
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "assignments")  # fixture has 3 rows
    assert res.status_code == 422
    assert "3" in res.text and "1" in res.text


# ── AC-RPT-33: cooperative cancel - re-reads status per checkpoint ──────────
def test_export_cooperative_cancel_stops_before_file(client, session_factory, fixture_ids):
    from modules.omnichannel.services.report_export_service import run_report_export

    db = session_factory()
    job = BackgroundJob(
        tenant_id=fixture_ids.tenant_id, type="omnichannel.report_export", status=JOB_ABORTED,
        payload_json={
            "workspaceId": fixture_ids.workspace_id, "reportKey": "users",
            **FIXTURE_RANGE, "tz": KL,
        },
    )
    db.add(job)
    db.commit()
    job_id = job.id

    run_report_export(db, job)
    db.refresh(job)
    assert job.status == JOB_ABORTED  # never overwritten to DONE
    assert not (job.result_json or {}).get("fileKey")
    db.close()

    h = _auth(client)
    assert _download(client, h, fixture_ids.workspace_id, "users", job_id).status_code == 404


# ── AC-RPT-34: uniform 404 matrix ────────────────────────────────────────────
def test_download_uniform_404_matrix(client, session_factory, fixture_ids):
    h = _auth(client)
    res = _export(client, h, fixture_ids.workspace_id, "conversations")
    job_id = res.json()["jobId"]

    # Bogus job id.
    assert _download(client, h, fixture_ids.workspace_id, "conversations", "not-a-job").status_code == 404

    # Wrong report key for a real job (payload.reportKey mismatch).
    assert _download(client, h, fixture_ids.workspace_id, "assignments", job_id).status_code == 404

    # Another tenant entirely - it has no workspace with this id at all, so
    # the workspace lookup itself 404s before the job lookup even runs.
    h2 = _other_tenant_auth(client, session_factory, slug="other-rpt-export")
    assert _download(client, h2, fixture_ids.workspace_id, "conversations", job_id).status_code == 404

    # A different workspace of the SAME tenant - job is workspace-scoped.
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    db = session_factory()
    other_ws = Workspace(
        tenant_id=fixture_ids.tenant_id, name="Report Export Second WS",
        status_id=statuses.status_id_for(db, fixture_ids.tenant_id, "WORKSPACE", "ACTIVE"),
    )
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()
    assert _download(client, h, other_ws_id, "conversations", job_id).status_code == 404

    # Not yet DONE.
    db = session_factory()
    pending_job = BackgroundJob(
        tenant_id=fixture_ids.tenant_id, type="omnichannel.report_export", status=JOB_PENDING,
        payload_json={"workspaceId": fixture_ids.workspace_id, "reportKey": "conversations"},
    )
    db.add(pending_job)
    db.commit()
    pending_id = pending_job.id
    db.close()
    assert _download(client, h, fixture_ids.workspace_id, "conversations", pending_id).status_code == 404


# ── AC-RPT-37/39: permission gates (core `reports.export`) ──────────────────
def test_export_permission_gate_403_reports_read_only(client, session_factory, fixture_ids):
    _role_with_keys(session_factory, ["reports.read"], email="reports-read-only@fixture.example")
    h_read_only = _auth(client, email="reports-read-only@fixture.example", password="pw12345678")
    h_admin = _auth(client)

    # The READ routes still work with only `reports.read`.
    assert client.get(
        f"{_base(fixture_ids.workspace_id)}/reports/meta", headers=h_read_only
    ).status_code == 200

    # BOTH export routes 403 without `reports.export`.
    res = _export(client, h_read_only, fixture_ids.workspace_id, "conversations")
    assert res.status_code == 403

    # A real job (created by an admin) still 403s the read-only role on
    # download.
    real = _export(client, h_admin, fixture_ids.workspace_id, "conversations")
    job_id = real.json()["jobId"]
    assert _download(client, h_read_only, fixture_ids.workspace_id, "conversations", job_id).status_code == 403


def test_export_permission_gate_403_no_permissions(client, session_factory, fixture_ids):
    _role_with_keys(session_factory, [], email="reports-no-perm@fixture.example")
    h_none = _auth(client, email="reports-no-perm@fixture.example", password="pw12345678")
    res = _export(client, h_none, fixture_ids.workspace_id, "conversations")
    assert res.status_code == 403


# ── AC-RPT-38: the demo tenant Admin already holds BOTH core keys (the
# existing sweep, not a new grant) ──────────────────────────────────────────
def test_demo_admin_has_reports_read_and_export_via_auth_me(client):
    h = _auth(client)
    res = client.get("/auth/me", headers=h)
    assert res.status_code == 200, res.text
    perms = set(res.json()["permissions"])
    assert "reports.read" in perms
    assert "reports.export" in perms


def test_freshly_provisioned_tenant_admin_has_reports_keys(client, session_factory):
    h = _other_tenant_auth(client, session_factory, slug="fresh-rpt-tenant")
    res = client.get("/auth/me", headers=h)
    perms = set(res.json()["permissions"])
    assert "reports.read" in perms
    assert "reports.export" in perms


# ── AC-RPT-40: uninstalling the module touches NO permission row - the
# module owns none of the `reports.*` rows ──────────────────────────────────
def test_uninstall_module_does_not_touch_core_reports_permissions(client, session_factory):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Uninstall RPT", slug="uninstall-rpt", admin_email="admin-uninstall-rpt@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    tenant_id = tenant.id
    db.commit()
    AppStoreService(db).install(tenant_id, "omnichannel")
    db.commit()

    before = {p.key: p.id for p in db.query(Permission).filter(Permission.key.in_(["reports.read", "reports.export"])).all()}
    assert set(before) == {"reports.read", "reports.export"}

    admin_role = db.query(Role).filter(Role.tenant_id == tenant_id, Role.name == "Admin").first()
    admin_perm_keys_before = {p.key for p in admin_role.permissions}
    assert "reports.read" in admin_perm_keys_before
    assert "reports.export" in admin_perm_keys_before

    AppStoreService(db).uninstall(tenant_id, "omnichannel", "omnichannel")
    db.commit()

    after = {p.key: p.id for p in db.query(Permission).filter(Permission.key.in_(["reports.read", "reports.export"])).all()}
    assert after == before  # same rows, untouched (module='core', never revoked-by-module)

    db.refresh(admin_role)
    admin_perm_keys_after = {p.key for p in admin_role.permissions}
    # The tenant's OWN grant on the core keys survives uninstall too - only
    # module-owned grants (`p.module == name`) are revoked in
    # `AppStoreService.uninstall`, and `reports.*` is module `core`.
    assert "reports.read" in admin_perm_keys_after
    assert "reports.export" in admin_perm_keys_after
    db.close()
