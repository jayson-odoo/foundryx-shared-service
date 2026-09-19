"""Sprint-5/10 S3 - Group C's authed operator routes: AC-10-37.

Wire-shape ruling from the orchestrator (2026-09-20): the plan never pins
these routes' shapes, and they are NOT the public gateway's Appendix A3
shapes (``snapshotId``/``entity: 'products'``/``companyCode``-as-top-level
are the S4 GATEWAY only). The Phase-1 contract for these AUTHED operator
routes is the frontend mock already shipped on this branch -
``service_frontend/types/autocount.ts`` (``AutocountPullSnapshot``,
``AutocountPullSnapshotRowsPage``) and
``service_frontend/services/autocount-service.real.ts`` (the exact paths /
methods / bodies for ``listPullSnapshots``/``getPullSnapshot``/
``getPullSnapshotRows``/``buildPullSnapshot``). Every route/shape below is
copied from those two files verbatim.

RED before the coder: none of these routes exist - every call 404s at the
FastAPI level (no matching route), which is the "missing feature" RED.

ASSUMED NAMES the coder must conform to:

* New router ``modules/autocount/routers/pull.py``, manifest entry
  ``{"name": "pull", "prefix": "/autocount/pull"}`` (the files list's own
  "routers/pull.py (new, authed operator routes)").
* ``POST /autocount/pull/snapshots {companyId, entityType}`` - permission
  ``autocount.pull.manage``, ``requested_via='operator'`` -> the SAME
  ``PullService.request_build`` the S3 build-job tests already pin. Status
  ``202`` (an async build, matching the gateway's own ``202`` in Appendix A3
  - the operator route's own status is unpinned by any AC, so this is the
  most literal reading, listed under ambiguities in the final report).
* ``GET /autocount/pull/snapshots?companyId=&entityType=&page=&page_size=``
  - permission ``autocount.pull.read`` -> ``{data: [...], total, page}``
  (the house list envelope, matching ``CompanyListResponse`` et al.).
* ``GET /autocount/pull/snapshots/{id}`` / ``GET
  /autocount/pull/snapshots/{id}/rows?page=&pageSize=`` - permission
  ``autocount.pull.read``.
* ``autocount.pull.read``/``autocount.pull.manage`` permission keys exist
  and are granted to the seeded tenant Admin by the time these tests run -
  the CSV rows themselves are AC-10-36 (S4), but the ROUTES are S3 and
  cannot be reached at all without them, so the coder must add them now;
  noted as an ambiguity in the final report, not silently assumed away.
* Every response field is camelCase per ``AutocountPullSnapshot``:
  ``id, entityType, companyId, companyCode, status, requestedVia, createdAt,
  extractedAt, expiresAt, recordCount, complete, contentHash,
  sourcePageSize, excludedCount, excludedRows`` (+ per-entity counters).

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.tenant import Tenant
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

OTHER_TENANT = "tenant-other-s10-pull"
NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _connection(db, *, tenant_id=DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id, *, tenant_id=DEFAULT_TENANT_ID) -> AcCompany:
    company = AcCompany(
        tenant_id=tenant_id, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID, record_count=1, status="ready"):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    if status == "ready":
        service.insert_row(
            tenant_id, snap, 0, company_id=company.id,
            source_ref="AED_SORENTO:A1", payload={"code": "A1", "list_price": "0.0"},
        )
        service.stamp_ready(
            tenant_id, snap, record_count=record_count, complete=True,
            content_hash="a" * 64, metadata={"excludedRows": [], "excludedCount": 0},
            extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
        )
    return snap


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── GET .../pull/snapshots (list) ────────────────────────────────────────────


def test_list_pull_snapshots_returns_the_house_list_envelope(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _snapshot(db, company)

    headers = _auth(client)
    response = client.get(
        "/autocount/pull/snapshots",
        params={"companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["entityType"] == ENTITY_PRODUCT
    assert body["data"][0]["companyId"] == company.id
    assert body["data"][0]["status"] == "ready"


# ── GET .../pull/snapshots/{id} (header) ─────────────────────────────────────


def test_get_pull_snapshot_returns_the_documented_header_shape(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _snapshot(db, company)

    headers = _auth(client)
    response = client.get(f"/autocount/pull/snapshots/{snap.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == snap.id
    assert body["status"] == "ready"
    assert body["companyCode"] == "SRT"
    assert body["recordCount"] == 1
    assert body["complete"] is True
    assert len(body["contentHash"]) == 64
    assert body["excludedCount"] == 0
    assert body["excludedRows"] == []


def test_get_pull_snapshot_404s_for_an_unknown_id(client, db):
    """A bare ``assert 404`` here would pass VACUOUSLY today (the route does
    not exist at all, so FastAPI's own routing 404 looks identical to an
    application-level "unknown snapshot" 404) - paired with a POSITIVE
    control in the SAME test (a snapshot that DOES exist, under the SAME
    route, resolves 200) so the test can only go green once the route is
    real AND distinguishes a genuine miss."""
    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _snapshot(db, company)
    headers = _auth(client)

    control = client.get(f"/autocount/pull/snapshots/{snap.id}", headers=headers)
    assert control.status_code == 200, control.text

    response = client.get("/autocount/pull/snapshots/does-not-exist", headers=headers)
    assert response.status_code == 404, response.text


def test_get_pull_snapshot_404s_cross_tenant(client, db):
    """AC-10-37: every query is tenant-scoped from the JWT - a snapshot that
    belongs to a DIFFERENT tenant must read exactly like an unknown one."""
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(Tenant(id=OTHER_TENANT, slug="other-s10-pull", name="Other Co", status_id=default_tenant.status_id))
        db.commit()
    conn = _connection(db, tenant_id=OTHER_TENANT)
    theirs = _company(db, conn.id, tenant_id=OTHER_TENANT)
    snap = _snapshot(db, theirs, tenant_id=OTHER_TENANT)

    headers = _auth(client)  # demo@example.com - DEFAULT_TENANT_ID
    response = client.get(f"/autocount/pull/snapshots/{snap.id}", headers=headers)
    assert response.status_code == 404, response.text


# ── GET .../pull/snapshots/{id}/rows (page) ──────────────────────────────────


def test_get_pull_snapshot_rows_returns_the_documented_page_shape(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _snapshot(db, company)

    headers = _auth(client)
    response = client.get(
        f"/autocount/pull/snapshots/{snap.id}/rows",
        params={"page": 1, "pageSize": 1000},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshotId"] == snap.id
    assert body["page"] == 1
    assert body["pageSize"] == 1000
    assert body["recordCount"] == 1
    assert body["rows"][0]["code"] == "A1"


# ── POST .../pull/snapshots (build as operator) ──────────────────────────────


def test_post_pull_snapshots_builds_and_returns_a_snapshot(client, db, monkeypatch):
    import httpx
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.models import AcEntityConfig, AcFieldMapping

    conn = _connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
                "watermarkField": None, "comparedFields": [], "distinctOf": None,
                "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
                "lookups": [],
            },
            last_preview_at=NOW, result_columns=["ItemCode"],
        )
    )
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True, sort_order=0,
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                  "Data": [{"ItemCode": "A1", "Description": "A1"}]},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    headers = _auth(client)
    response = client.post(
        "/autocount/pull/snapshots",
        json={"companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["entityType"] == ENTITY_PRODUCT
    assert body["companyId"] == company.id


def test_pull_routes_require_permission_not_just_authentication(client, db):
    """CONTROL: a user with NO autocount.pull.* grant is 403, proving the
    route is genuinely permission-gated rather than merely
    authentication-gated (a route that only checked ``get_current_user``
    would make every OTHER assertion in this file pass for the wrong
    reason)."""
    from app.repositories.permission_repository import PermissionRepository
    from app.models import Role, User, UserStatus
    from app.security import hash_password
    from sqlalchemy.sql import func

    role = Role(tenant_id=DEFAULT_TENANT_ID, name="No Pull Access", description="")
    role.permissions = [
        p for p in PermissionRepository(db).list_all() if p.key == "autocount.companies.read"
    ]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email="nopull@example.com",
        password=hash_password("limited1234"), name="No Pull",
        status=UserStatus.ACTIVE.value, email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()

    headers = _auth(client, "nopull@example.com", "limited1234")
    response = client.get("/autocount/pull/snapshots", headers=headers)
    assert response.status_code == 403, response.text


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_get_pull_snapshot_404s_cross_tenant dies if the router/service
#   resolves the snapshot with an unscoped ``get_by_id`` (the polymorphic-id
#   leak class this repo has hit twice already).
# * test_pull_routes_require_permission_not_just_authentication dies if the
#   route is gated on ``get_current_user`` alone (every happy-path test in
#   this file would then ALSO pass with no permission check at all).
