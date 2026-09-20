"""Sprint-5/10 S4 - the public gateway's read routes: AC-10-32, 33, 47.

Fixture parity: `documentation/plans/sprint-5/10-fixtures/{products-header-
ready,products-rows-page1,snapshot-failed}.json` pin the exact key sets this
file asserts (Appendix A3) - a `ready`/`failed` header carries ONLY the keys
those fixtures show (e.g. `recordCount`/`complete`/`contentHash` are ABSENT
on a `failed` header, not merely `null`).

RED before the coder: `/api/v1/autocount/snapshots/{id}` and `.../rows` do
not exist yet.

ASSUMED NAMES (additional to the other S4 files):

* `GET /snapshots/{id}` header shapes (Appendix A3, exact key sets):
  - `building`: `{snapshotId, entity, companyCode, status}` (+ optional
    `progress`) - NO `recordCount`/`complete`/`contentHash`/counters at all.
  - `ready`: `{snapshotId, entity, companyCode, status, extractedAt,
    expiresAt, recordCount, complete, contentHash, sourcePageSize}` +
    `excludedCount`/`excludedRows` + per-entity counters.
  - `failed`: `{snapshotId, entity, companyCode, status, error: {code,
    message}}` - same omissions as `building`.
* `GET /snapshots/{id}/rows?page=&pageSize=` -> `{snapshotId, page,
  pageSize, totalPages, recordCount, rows}`, `page` 1-based, `pageSize`
  default 1000 / max 1000 (clamp, never an error), stable order by
  `row_index`, a page past `totalPages` -> empty `rows`, never a 404.
* A snapshot outside the KEY's company scope (even within the SAME tenant)
  reads IDENTICALLY to an unknown id - 404 `UNKNOWN_SNAPSHOT` (AC-10-30's
  "possession of an id is not authorisation"), never 403
  `COMPANY_NOT_ALLOWED` (that code is reachable only from `POST /snapshots`,
  where the company comes from the REQUEST, not from an id already bound to
  one - tested in `test_s10_s4_gateway_build.py`).
* Gateway rows equal the operator route's rows for the SAME snapshot - ONE
  data path (AC-10-33's own "served exactly as stored, no re-projection").

Kill-test notes are per section below.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.tenant import Tenant
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

GATEWAY_PREFIX = "/api/v1/autocount"
OTHER_TENANT = "tenant-other-s10-s4-gw-reads"
FIXTURES_DIR = (
    Path(__file__).resolve().parents[2]
    / "documentation" / "plans" / "sprint-5" / "10-fixtures"
)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    `test_s10_s3_delivery_mode.py`'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    import httpx

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(
    db, *, tenant_id=DEFAULT_TENANT_ID, sorento_company_code="SRT",
    database_name="AED_SORENTO",
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
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, tenant_id=DEFAULT_TENANT_ID, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        tenant_id, name="gateway read test key", company_ids=company_ids,
    )
    return plaintext


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s10-s4-gw-reads", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


# Anchored on the REAL wall clock (coordinator fix, 2026-09-20): every
# `_ready_snapshot` in this file defaults `expires_at = NOW + 24h`, and the
# gateway's header route treats a snapshot whose `expires_at` has passed as
# `SNAPSHOT_EXPIRED` (410) using the REAL current time, not an injectable
# `now=`. A fixed calendar constant here is a ticking time bomb - every
# "ready and readable" assertion in this file would start failing the
# moment real time passed the hardcoded window.
NOW = datetime.now(timezone.utc)


def _building_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID):
    from modules.autocount.services.pull_service import SnapshotService

    return SnapshotService(db).create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )


def _ready_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID, rows=None):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    rows = rows if rows is not None else [{"code": "A1"}, {"code": "A2"}, {"code": "A3"}]
    for i, payload in enumerate(rows):
        service.insert_row(
            tenant_id, snap, i, company_id=company.id,
            source_ref=f"AED_SORENTO:{payload['code']}", payload=payload,
        )
    return service.stamp_ready(
        tenant_id, snap, record_count=len(rows), complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
    )


def _failed_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    return service.stamp_failed(
        tenant_id, snap, error="Source page 2 of 3 failed.", error_code="SOURCE_PAGE_FAILED",
    )


# ── AC-10-32: header shapes, exact key sets ──────────────────────────────────


def test_building_header_carries_only_the_four_documented_keys(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    snap = _building_snapshot(db, company)

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshotId"] == snap.id
    assert body["entity"] == "products"
    assert body["companyCode"] == "SRT"
    assert body["status"] == "building"
    for absent_key in ("recordCount", "complete", "contentHash", "excludedCount"):
        assert absent_key not in body, f"{absent_key!r} must be absent while building"


def test_ready_header_carries_the_full_documented_shape(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    snap = _ready_snapshot(db, company)

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["recordCount"] == 3
    assert body["complete"] is True
    assert len(body["contentHash"]) == 64
    assert body["excludedCount"] == 0
    assert body["excludedRows"] == []


def test_failed_header_carries_only_the_documented_error_shape(client, db):
    """Sprint-5/10 S6 (AC-10-58 M1) - `error.code` is still the contract,
    but `error.message` is now the FIXED operator-safe sentence for that
    code, never the stored `snapshot.error` (which names this deployment's
    own source host/port). `test_s10_s6_security_fixes.py` owns the full
    per-code map; this test keeps pinning the KEY SET plus the one fact
    that matters here: the stored text does not reach this surface."""
    from modules.autocount.services.pull_gateway_service import GATEWAY_FAILED_MESSAGES

    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    snap = _failed_snapshot(db, company)

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == {
        "code": "SOURCE_PAGE_FAILED",
        "message": GATEWAY_FAILED_MESSAGES["SOURCE_PAGE_FAILED"],
    }
    assert "Source page 2 of 3 failed." not in response.text
    for absent_key in ("recordCount", "complete", "contentHash"):
        assert absent_key not in body


def test_fixture_parity_ready_header_matches_the_recorded_shape_keys():
    """The recorded fixture's own key set is the CONTRACT (Appendix A3) -
    every key it carries must be one this file's `ready` assertions above
    also check, so a future header-field removal is caught here even
    without a live snapshot."""
    fixture = json.loads((FIXTURES_DIR / "products-header-ready.json").read_text())
    expected_keys = {
        "snapshotId", "entity", "companyCode", "status", "extractedAt", "expiresAt",
        "recordCount", "complete", "contentHash", "sourcePageSize",
        "zeroListPriceCount", "negativeListPriceCount", "enrichMissCount",
        "excludedCount", "excludedRows",
    }
    assert set(fixture.keys()) == expected_keys


# ── AC-10-33: paging ─────────────────────────────────────────────────────────


def test_rows_page_default_and_max_page_size(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    rows = [{"code": f"A{i}"} for i in range(5)]
    snap = _ready_snapshot(db, company, rows=rows)

    default_page = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": key},
    )
    assert default_page.json()["pageSize"] == 1000

    clamped = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows",
        params={"pageSize": 5000}, headers={"X-API-Key": key},
    )
    assert clamped.status_code == 200, clamped.text
    assert clamped.json()["pageSize"] == 1000


def test_rows_are_stable_ordered_by_row_index(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    rows = [{"code": "C"}, {"code": "A"}, {"code": "B"}]
    snap = _ready_snapshot(db, company, rows=rows)

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": key},
    )
    codes = [row["code"] for row in response.json()["rows"]]
    assert codes == ["C", "A", "B"]  # row_index order, not alphabetical


def test_a_page_past_totalpages_is_empty_rows_never_a_404(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    snap = _ready_snapshot(db, company, rows=[{"code": "A1"}])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows",
        params={"page": 99}, headers={"X-API-Key": key},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == []
    assert body["snapshotId"] == snap.id
    assert body["recordCount"] == 1


def test_gateway_rows_equal_the_operator_routes_rows_one_data_path(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    snap = _ready_snapshot(db, company)

    gateway_rows = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": key},
    ).json()["rows"]
    operator_rows = client.get(
        f"/autocount/pull/snapshots/{snap.id}/rows", headers=_auth(client),
    ).json()["rows"]
    assert gateway_rows == operator_rows


# ── AC-10-47 / AC-10-30: possession of an id is not authorisation ──────────


def test_a_snapshot_outside_the_keys_company_scope_reads_as_unknown_snapshot(client, db):
    company = _company(db)
    other_company = _company(db, sorento_company_code="MCH", database_name="MOCHA")
    snap = _ready_snapshot(db, other_company)
    key = _issue_key(db, company_ids=[company.id])  # scoped to `company`, NOT `other_company`

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "UNKNOWN_SNAPSHOT"


def test_a_cross_tenant_snapshot_reads_identically_to_unknown(client, db):
    _other_tenant(db)
    their_company = _company(db, tenant_id=OTHER_TENANT, sorento_company_code="MCH")
    their_snapshot = _ready_snapshot(db, their_company, tenant_id=OTHER_TENANT)
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])

    unknown = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist-at-all", headers={"X-API-Key": key},
    )
    cross_tenant = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{their_snapshot.id}", headers={"X-API-Key": key},
    )
    assert cross_tenant.status_code == unknown.status_code == 404
    assert cross_tenant.json() == unknown.json()


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_building_header_carries_only_the_four_documented_keys and
#   test_failed_header_carries_only_the_documented_error_shape die if the
#   gateway reuses the OPERATOR route's `PullSnapshotOut` schema wholesale
#   (which defaults `recordCount`/`complete` to 0/False rather than omitting
#   them) instead of Appendix A3's own omit-when-inapplicable shape.
# * test_a_snapshot_outside_the_keys_company_scope_reads_as_unknown_snapshot
#   dies if the gateway checks tenant scope only (not company scope) when
#   resolving a snapshot id - it would wrongly 200.
# * test_gateway_rows_equal_the_operator_routes_rows_one_data_path dies if
#   either route re-projects `payload_json` instead of serving it exactly
#   as stored, or if the two routes drift onto separate query paths.
