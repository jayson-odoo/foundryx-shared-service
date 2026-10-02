"""Sprint-5/10 S4 security round 1 - HIGH 1: unhandled exceptions must never
escape the gateway as a bare 500.

PROVEN (independent Opus security review, PoC pytest in a throwaway
worktree): a valid key requesting a huge `page` on
`GET /snapshots/{id}/rows` hits an `OverflowError` (SQLite) / Postgres
"OFFSET must be bigint" deep inside the row-page query, which core's default
exception handling turns into a bare 500 with no flat Appendix A6 envelope,
no audit row, and (if `settings.debug` is ever on) a traceback in the body.
The same door exists for ANY unexpected exception on any of the three
routes, named here as `CompanyNotFound` racing inside
`PullService.request_build`.

RED before the fix: every test below currently either 500s with a
non-Appendix-A6 body, or (the giant page) raises before any response is
built at all.

ASSUMED NAMES (this coder's own fix, not previously pinned):
* A stable code `INTERNAL` for the generic 500 catch-all.
* `page` is rejected (422 `INVALID_REQUEST`) above `10**6` - never silently
  clamped like `pageSize`, and never reaches the repository layer.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig

GATEWAY_PREFIX = "/api/v1/autocount"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network."""
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


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id, *, sorento_company_code="SRT") -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="sec-internal-errors key", company_ids=company_ids,
    )
    return _key, plaintext


def _ready_snapshot(db, company):
    from modules.autocount.services.pull_service import SnapshotService
    from datetime import datetime, timedelta, timezone

    service = SnapshotService(db)
    now = datetime.now(timezone.utc)
    snap = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, snap, 0, company_id=company.id,
        source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    return service.stamp_ready(
        DEFAULT_TENANT_ID, snap, record_count=1, complete=True, content_hash="a" * 64,
        metadata={"excludedCount": 0, "excludedRows": []},
        extracted_at=now, expires_at=now + timedelta(hours=1),
    )


# ── the giant page: 422, never an OverflowError/500 ─────────────────────────


def test_a_giant_page_is_a_flat_422_never_an_unhandled_error(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _ready_snapshot(db, company)
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows",
        params={"page": "9999999999999999999999999"},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "error" not in body
    assert body.get("code")
    assert body.get("message")


def test_a_giant_page_still_writes_one_audit_row(client, db):
    from modules.autocount.models import AcPullAudit

    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _ready_snapshot(db, company)
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    before = db.query(AcPullAudit).count()
    client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows",
        params={"page": "9999999999999999999999999"},
        headers={"X-API-Key": plaintext},
    )
    after = db.query(AcPullAudit).count()
    assert after == before + 1


def test_a_page_of_exactly_the_maximum_is_still_accepted_control(client, db):
    """CONTROL: the bound must reject only ABOVE the maximum, never a
    legitimate (if silly) in-range page."""
    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _ready_snapshot(db, company)
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows",
        params={"page": 1000000},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []


# ── any other unexpected exception -> flat 500 + audit, never a bare crash ──


def _assert_internal_500(response, before_count, after_count):
    assert response.status_code == 500, response.text
    body = response.json()
    assert "error" not in body
    assert body["code"] == "INTERNAL"
    assert body.get("message")
    # nothing internal (traceback, exception class name, SQL) in the body
    blob = response.text
    assert "Traceback" not in blob
    assert "sqlalchemy" not in blob.lower()
    assert after_count == before_count + 1


def test_build_route_forced_internal_exception_is_flat_500_with_audit(client, db, monkeypatch):
    from modules.autocount.models import AcPullAudit
    from modules.autocount.services import pull_gateway_service

    conn = _connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": company.connection_id, "path": "/itembypage",
                "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
                "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
                "reconcileAt": "02:00", "lookups": [],
            },
        )
    )
    db.commit()
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    def _boom(self, tenant_id, company_id, internal_entity):
        raise RuntimeError("forced failure for the security test")

    monkeypatch.setattr(pull_gateway_service.PullGatewayService, "build", _boom)

    before = db.query(AcPullAudit).count()
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": plaintext},
    )
    after = db.query(AcPullAudit).count()
    _assert_internal_500(response, before, after)


def test_get_header_route_forced_internal_exception_is_flat_500_with_audit(
    client, db, monkeypatch,
):
    from modules.autocount.models import AcPullAudit
    from modules.autocount.services import pull_gateway_service

    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _ready_snapshot(db, company)
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    def _boom(self, key_row, snapshot_id):
        raise RuntimeError("forced failure for the security test")

    monkeypatch.setattr(
        pull_gateway_service.PullGatewayService, "get_snapshot_for_key", _boom
    )

    before = db.query(AcPullAudit).count()
    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": plaintext},
    )
    after = db.query(AcPullAudit).count()
    _assert_internal_500(response, before, after)


def test_get_rows_route_forced_internal_exception_is_flat_500_with_audit(
    client, db, monkeypatch,
):
    from modules.autocount.models import AcPullAudit
    from modules.autocount.services import pull_gateway_service

    conn = _connection(db)
    company = _company(db, conn.id)
    snap = _ready_snapshot(db, company)
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    def _boom(self, snapshot, *, page, page_size):
        raise RuntimeError("forced failure for the security test")

    monkeypatch.setattr(pull_gateway_service.PullGatewayService, "rows_page", _boom)

    before = db.query(AcPullAudit).count()
    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": plaintext},
    )
    after = db.query(AcPullAudit).count()
    _assert_internal_500(response, before, after)


# ── CompanyNotFound races to the contract's 404, never a bare 500 ──────────


def test_company_not_found_race_inside_request_build_is_unknown_company_404(
    client, db, monkeypatch,
):
    from modules.autocount.services.company_service import CompanyNotFound
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": company.connection_id, "path": "/itembypage",
                "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
                "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
                "reconcileAt": "02:00", "lookups": [],
            },
        )
    )
    db.commit()
    _key, plaintext = _issue_key(db, company_ids=[company.id])

    def _vanished(self, tenant_id, company_id, entity_type, **kwargs):
        raise CompanyNotFound("That AutoCount company was not found.")

    monkeypatch.setattr(PullService, "request_build", _vanished)

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "UNKNOWN_COMPANY"


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_a_giant_page_is_a_flat_422_never_an_unhandled_error dies if `page`
#   is parsed with a bare `int()` and no upper bound, or if the bound is
#   only applied to `pageSize` (the actual reported vulnerability path).
# * The three forced-internal-exception tests die if any route's
#   `except PullGatewayError` is the ONLY handler (an unrelated exception
#   would propagate to FastAPI's default handler - a bare `{"detail": ...}`
#   500, not this file's flat body - and would not write an audit row).
# * test_company_not_found_race_inside_request_build_is_unknown_company_404
#   dies if `PullGatewayService.build` does not translate `CompanyNotFound`.
