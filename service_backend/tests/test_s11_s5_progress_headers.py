"""Sprint-5/11 S5 - AC-11-41 (the public gateway's `building` header carries
`progress`) and AC-11-42 (the operator `PullSnapshotOut.progress`, closing
BL-SS-236 - `progress` had landed on NEITHER header before this slice).

Both surfaces project the SAME three fields (`pagesDone`, `pagesTotal`,
`stage`), read off the snapshot's own `job_id` row, tenant-scoped - and
OMIT the key entirely (never `null`) whenever nothing useful is known:
before page 1 answers, a bare-array endpoint (no page count ever), a
`ready`/`failed` snapshot, or a job belonging to a DIFFERENT tenant than
the one resolving the snapshot (a leak this file treats as seriously as any
other cross-tenant read).

RED-now design note: with NOTHING built yet, every "progress omitted"
assertion below would trivially pass on today's code (nothing projects
`progress` at all) - which would not be RED for the right reason. Every
omission test below therefore opens with a `_known_progress_control` call
against a SIBLING snapshot/company in the SAME key/tenant scope, proving
the POSITIVE projection first - that control assertion is what makes the
whole test genuinely fail today, and it must keep passing once the coder
implements the feature.

Snapshot fixtures mirror `test_s10_s4_gateway_reads.py`'s own
`_building_snapshot`/`_issue_key` helpers; the gateway route/prefix mirror
`test_s10_s6_security_fixes.py`'s `GATEWAY_PREFIX`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_RUNNING, BackgroundJob
from app.models.connection import Connection
from app.models.tenant import Tenant
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

GATEWAY_PREFIX = "/api/v1/autocount"
OTHER_TENANT = "tenant-other-s11-s5-progress-headers"
OTHER_TENANT_SLUG = "other-s11-s5-progress-headers"
PULL_JOB_TYPE = "autocount_pull_snapshot"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(
    db, *, tenant_id: str = DEFAULT_TENANT_ID, database_name: str, code: str = "SRT"
) -> AcCompany:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code=code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, tenant_id: str = DEFAULT_TENANT_ID, company_ids) -> str:
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        tenant_id, name="s11-s5 progress header key", company_ids=company_ids,
    )
    return plaintext


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _building_snapshot(db, company, *, tenant_id: str = DEFAULT_TENANT_ID):
    from modules.autocount.services.pull_service import SnapshotService

    return SnapshotService(db).create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )


def _job(
    db, *, tenant_id: str = DEFAULT_TENANT_ID, done: int = 0, total: int = 0,
    stage: Optional[str] = None,
) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=tenant_id, type=PULL_JOB_TYPE, status=JOB_RUNNING, payload_json={},
        progress_done=done, progress_total=total,
        cursor_json=({"stage": stage} if stage else None),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug=OTHER_TENANT_SLUG, name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _known_progress_control(client, key: str, db, company) -> None:
    """Proves the POSITIVE projection against a sibling snapshot in the SAME
    key scope - see module docstring. Asserted with the exact house pin
    (`{"pagesDone": ..., "pagesTotal": ..., "stage": ...}`)."""
    snap = _building_snapshot(db, company)
    job = _job(db, done=1, total=2, stage="source")
    snap.job_id = job.id
    db.commit()

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    assert response.json().get("progress") == {
        "pagesDone": 1, "pagesTotal": 2, "stage": "source",
    }, response.json()


# ── AC-11-41: the public gateway's `building` header ────────────────────────


def test_gateway_building_header_carries_progress_when_known(client, db):
    company = _company(db, database_name="S11S5HDRKNOWN")
    key = _issue_key(db, company_ids=[company.id])
    snap = _building_snapshot(db, company)
    job = _job(db, done=2, total=5, stage="source")
    snap.job_id = job.id
    db.commit()

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "building"
    assert body.get("progress") == {
        "pagesDone": 2, "pagesTotal": 5, "stage": "source",
    }, body


def test_gateway_building_header_omits_progress_before_page_one_answers(client, db):
    control_company = _company(db, database_name="S11S5HDRCTRL1")
    target_company = _company(db, database_name="S11S5HDRTGT1")
    key = _issue_key(db, company_ids=[control_company.id, target_company.id])
    _known_progress_control(client, key, db, control_company)

    snap = _building_snapshot(db, target_company)
    job = _job(db, done=0, total=0, stage=None)  # no beat has landed yet
    snap.job_id = job.id
    db.commit()

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "building"
    assert "progress" not in body, body


def test_gateway_building_header_omits_progress_for_a_bare_array_endpoint(client, db):
    control_company = _company(db, database_name="S11S5HDRCTRL2")
    target_company = _company(db, database_name="S11S5HDRTGT2")
    key = _issue_key(db, company_ids=[control_company.id, target_company.id])
    _known_progress_control(client, key, db, control_company)

    # A bare-array endpoint never echoes `TotalPages` - `beat_progress`'s own
    # `total=None` leaves `progress_total` at its unset default even though a
    # `stage` (and a `done` count) IS known; AC-11-41's own text: "for a
    # bare-array endpoint" is a NAMED omission case, distinct from "before
    # page 1 answers".
    snap = _building_snapshot(db, target_company)
    job = _job(db, done=1, total=0, stage="source")
    snap.job_id = job.id
    db.commit()

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "progress" not in body, body


def test_gateway_ready_and_failed_headers_never_carry_progress(client, db):
    from modules.autocount.services.pull_service import SnapshotService

    control_company = _company(db, database_name="S11S5HDRCTRL3")
    ready_company = _company(db, database_name="S11S5HDRREADY")
    failed_company = _company(db, database_name="S11S5HDRFAILED")
    key = _issue_key(
        db, company_ids=[control_company.id, ready_company.id, failed_company.id]
    )
    _known_progress_control(client, key, db, control_company)

    service = SnapshotService(db)
    now = datetime.now(timezone.utc)

    ready_snap = service.create_building(
        DEFAULT_TENANT_ID, ready_company.id, ENTITY_PRODUCT,
        company_code=ready_company.sorento_company_code, requested_via="gateway",
    )
    ready_job = _job(db, done=1, total=1, stage="source")
    ready_snap.job_id = ready_job.id
    db.commit()
    ready_snap = service.stamp_ready(
        DEFAULT_TENANT_ID, ready_snap, record_count=0, complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=now, expires_at=now + timedelta(hours=24),
    )

    failed_snap = service.create_building(
        DEFAULT_TENANT_ID, failed_company.id, ENTITY_PRODUCT,
        company_code=failed_company.sorento_company_code, requested_via="gateway",
    )
    failed_job = _job(db, done=1, total=3, stage="source")
    failed_snap.job_id = failed_job.id
    db.commit()
    failed_snap = service.stamp_failed(
        DEFAULT_TENANT_ID, failed_snap, error="boom", error_code="SOURCE_PAGE_FAILED",
    )

    ready_response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{ready_snap.id}", headers={"X-API-Key": key}
    )
    assert ready_response.status_code == 200, ready_response.text
    ready_body = ready_response.json()
    assert ready_body["status"] == "ready"
    assert "progress" not in ready_body, ready_body

    failed_response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{failed_snap.id}", headers={"X-API-Key": key}
    )
    assert failed_response.status_code == 200, failed_response.text
    failed_body = failed_response.json()
    assert failed_body["status"] == "failed"
    assert "progress" not in failed_body, failed_body


def test_gateway_building_header_never_leaks_another_tenants_job_progress(client, db):
    _other_tenant(db)
    control_company = _company(db, database_name="S11S5HDRCTRL4")
    target_company = _company(db, database_name="S11S5HDRTGT4")
    key = _issue_key(db, company_ids=[control_company.id, target_company.id])
    _known_progress_control(client, key, db, control_company)

    # A data anomaly the resolver must defend against regardless of how it
    # could arise: the snapshot's own `job_id` points at a job belonging to
    # a DIFFERENT tenant. The job must be resolved WITH the API key row's
    # own tenant (AC-11-71) - never another tenant's numbers leaked through.
    snap = _building_snapshot(db, target_company)
    foreign_job = _job(db, tenant_id=OTHER_TENANT, done=9, total=10, stage="source")
    snap.job_id = foreign_job.id
    db.commit()

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "progress" not in body, body


# ── AC-11-42: the operator `PullSnapshotOut.progress` ───────────────────────


def test_operator_pull_snapshot_out_carries_progress_when_known(client, db):
    company = _company(db, database_name="S11S5OPKNOWN")
    snap = _building_snapshot(db, company)
    job = _job(db, done=3, total=12, stage="lookup:uom")
    snap.job_id = job.id
    db.commit()

    response = client.get(f"/autocount/pull/snapshots/{snap.id}", headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("progress") == {
        "pagesDone": 3, "pagesTotal": 12, "stage": "lookup:uom",
    }, body


def test_operator_pull_snapshot_list_and_detail_omit_progress_when_unknown(client, db):
    known_company = _company(db, database_name="S11S5OPCTRL")
    target_company = _company(db, database_name="S11S5OPTARGET")

    known_snap = _building_snapshot(db, known_company)
    known_job = _job(db, done=1, total=2, stage="source")
    known_snap.job_id = known_job.id
    db.commit()

    control = client.get(
        f"/autocount/pull/snapshots/{known_snap.id}", headers=_auth(client)
    )
    assert control.status_code == 200, control.text
    assert control.json().get("progress") == {
        "pagesDone": 1, "pagesTotal": 2, "stage": "source",
    }, control.json()

    target_snap = _building_snapshot(db, target_company)
    target_job = _job(db, done=0, total=0, stage=None)
    target_snap.job_id = target_job.id
    db.commit()

    detail = client.get(
        f"/autocount/pull/snapshots/{target_snap.id}", headers=_auth(client)
    )
    assert detail.status_code == 200, detail.text
    assert "progress" not in detail.json(), detail.json()

    listed = client.get(
        "/autocount/pull/snapshots",
        params={"companyId": target_company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert rows and rows[0]["id"] == target_snap.id
    assert "progress" not in rows[0], rows[0]
