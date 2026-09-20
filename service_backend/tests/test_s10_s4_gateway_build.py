"""Sprint-5/10 S4 - the public gateway's build route: AC-10-29, and every
AC-10-31 error code REACHABLE from `POST /snapshots` (401, 403x2, 404, 409x2,
429) - the one route where `companyCode`/`entity` are ALWAYS available from
the request body, so the full flat body `{code,message,companyCode,entity}`
is asserted strictly here (Appendix A2/A3/A6).

RED before the coder: `/api/v1/autocount/snapshots` does not exist yet.

ASSUMED NAMES (additional to `test_s10_s4_gateway_auth_and_throttle.py`):

* `POST /api/v1/autocount/snapshots {companyCode, entity}` -> `202
  {snapshotId, status, entity, companyCode}`. `entity` on the wire is
  `products`/`stock_balances`, translated 1:1 to the internal
  `product`/`stock_balance` canonical keys by ONE map (plan §2.5); an
  unrecognised wire value is a 422 naming the accepted set.
* `companyCode` resolves case-insensitively and TRIMMED against
  `ac_company.sorento_company_code` WITHIN the key's tenant only, and the
  resolved company id must be IN the key's `company_ids` (AC-10-30).
* Error codes reachable from this route, each with the full flat body:
  401 `INVALID_API_KEY`, 403 `SERVICE_NOT_ENABLED`, 403
  `COMPANY_NOT_ALLOWED`, 404 `UNKNOWN_COMPANY`, 409 `PULL_NOT_ENABLED`, 409
  `PUSH_ACTIVE`, 429 `TOO_MANY_BUILDS` (+ `Retry-After`).
* Re-attach (AC-10-26 via the gateway): a second `POST` while a build is
  still `building` for the same (company, entity) returns the SAME
  `snapshotId`.

Under this suite's eager job execution, the enqueued build usually FINISHES
before the route returns (a fast `httpx.MockTransport` stub completes in
milliseconds) - so this file asserts the 202 STATUS CODE + the envelope
fields Appendix A3 pins (`snapshotId`/`entity`/`companyCode`), never the
transient `status: "building"` value a slow real build would still be
showing when a consumer's poll actually lands (that timing is not
reproducible under eager settings and is not what AC-10-29 itself pins).

Coordinator ruling 2026-09-20 (was an ambiguity, now settled): Appendix A6
governs even a NATIVE pydantic request-validation failure on this gateway -
the flat `{code,message,companyCode,entity}` shape applies there too, never
core's global `{"error": {...}}` `/api/v1/*` wrapper
(`app/api_errors.py::install_api_error_handler`'s `RequestValidationError`
handler).

Kill-test notes are per section below.
"""
from __future__ import annotations

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig

GATEWAY_PREFIX = "/api/v1/autocount"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    `test_s10_s3_delivery_mode.py`'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
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


def _company(
    db, connection_id, *, sorento_company_code="SRT", database_name="AED_SORENTO",
) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _pull_task(db, company, *, etl_status="active", delivery_mode="pull") -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=etl_status, delivery_mode=delivery_mode,
        source_config={
            "connectionId": company.connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="gateway build test key", company_ids=company_ids,
    )
    return plaintext


def _stub_empty_transport(monkeypatch) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )


# ── AC-10-29: happy path, entity wire translation ────────────────────────────


def test_build_returns_202_with_the_documented_envelope(client, db, monkeypatch):
    _stub_empty_transport(monkeypatch)
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["snapshotId"]
    assert body["entity"] == "products"
    assert body["companyCode"] == "SRT"


def test_an_unrecognised_entity_is_a_422_naming_the_accepted_set(client, db):
    """The coder's own two additive validation codes (coordinator message,
    2026-09-20) - NEITHER is in Appendix A6's table, which only pins the 9
    codes reachable AFTER a request parses cleanly. Noted here, once, for
    whoever next edits the cross-repo contract docs: `UNKNOWN_ENTITY` (this
    test) and `INVALID_REQUEST` (the sibling test below) need adding to the
    Sorento-facing addendum alongside the existing ladder."""
    conn = _connection(db)
    company = _company(db, conn.id)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "widgets"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 422, response.text
    # Coordinator ruling 1 (2026-09-20): flat everywhere on this gateway,
    # INCLUDING request-validation failures - never core's `{"error": {...}}`
    # wrapper (`app/api_errors.py`'s global `RequestValidationError` handler,
    # which every OTHER `/api/v1/*` route gets).
    body = response.json()
    assert "error" not in body
    assert body["code"] == "UNKNOWN_ENTITY"
    assert "products" in body["message"] and "stock_balances" in body["message"]


def test_a_malformed_request_body_is_still_the_flat_envelope_never_cores_wrapper(client, db):
    """Coordinator ruling 1: a missing/wrong-typed field (here `entity`
    omitted entirely) is a NATIVE pydantic body-validation failure - the
    kind `app/api_errors.py`'s global handler would otherwise wrap as
    `{"error": {"code": "invalid_request", ...}}` for every OTHER
    `/api/v1/*` route. This gateway must still answer flat, with the coder's
    own additive `INVALID_REQUEST` code (NOT in Appendix A6's table - see
    the sibling test above's note; needs adding to the contract docs)."""
    conn = _connection(db)
    company = _company(db, conn.id)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT"},  # `entity` missing entirely
        headers={"X-API-Key": key},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "error" not in body, (
        "the core /api/v1/* envelope leaked through - this route must "
        "answer the flat Appendix A6 shape even for a native validation "
        "failure, per the coordinator's ruling"
    )
    assert body["code"] == "INVALID_REQUEST"
    assert body.get("message")


def test_company_code_resolves_case_insensitively_and_trimmed(client, db, monkeypatch):
    _stub_empty_transport(monkeypatch)
    conn = _connection(db)
    company = _company(db, conn.id, sorento_company_code="SRT")
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": " srt ", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text


# ── AC-10-26 via the gateway: re-attach ──────────────────────────────────────


def test_a_build_already_in_flight_reattaches_to_the_same_snapshot_id(client, db):
    from modules.autocount.services.pull_service import SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])
    in_flight = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text
    assert response.json()["snapshotId"] == in_flight.id


# ── AC-10-31 error codes reachable from this route (full flat body) ────────


def _assert_flat_error(response, *, status, code, company_code="SRT", entity="products"):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["message"]
    assert body["companyCode"] == company_code
    assert body["entity"] == entity


def test_401_invalid_api_key_full_body(client, db):
    conn = _connection(db)
    _company(db, conn.id)
    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": "fxa_live_" + "z" * 43},
    )
    _assert_flat_error(response, status=401, code="INVALID_API_KEY")


def test_403_service_not_enabled_full_body(client, db):
    from app.services.app_store_service import AppStoreService

    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "autocount")

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=403, code="SERVICE_NOT_ENABLED")


def test_403_company_not_allowed_full_body(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    other_conn = _connection(db)
    other_company = _company(
        db, other_conn.id, sorento_company_code="MCH", database_name="MOCHA",
    )
    # Key scoped to `other_company` only - `company` (SRT) is a real
    # company in this key's OWN tenant, just outside its explicit scope.
    key = _issue_key(db, company_ids=[other_company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=403, code="COMPANY_NOT_ALLOWED")


def test_404_unknown_company_full_body(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "XYZ", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=404, code="UNKNOWN_COMPANY", company_code="XYZ")


def test_409_pull_not_enabled_when_no_task_exists_full_body(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")


def test_409_pull_not_enabled_when_task_is_draft_full_body(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company, etl_status="draft")
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=409, code="PULL_NOT_ENABLED")


def test_409_push_active_full_body(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company, etl_status="active", delivery_mode="push")
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=409, code="PUSH_ACTIVE")


def test_429_too_many_builds_full_body_with_retry_after(client, db):
    from datetime import datetime, timedelta, timezone

    from modules.autocount.services.pull_service import SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])
    now = datetime.now(timezone.utc)
    recent = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, recent, record_count=1, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=now - timedelta(seconds=10), expires_at=now + timedelta(hours=24),
    )

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    _assert_flat_error(response, status=429, code="TOO_MANY_BUILDS")
    assert response.headers.get("Retry-After")


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_403_company_not_allowed_full_body dies if the gateway resolves
#   `companyCode` against ANY company in the tenant instead of intersecting
#   with the key's own `company_ids` - the fixture deliberately makes `SRT`
#   a REAL company in the SAME tenant, just outside this key's scope, so a
#   tenant-only check would wrongly 202 instead of 403.
# * test_company_code_resolves_case_insensitively_and_trimmed dies if the
#   match is exact-case/untrimmed - a real consumer integration detail
#   (Appendix A2's own worked example uses exact-case `SRT`/`MCH`, but the
#   match rule itself is explicitly case-insensitive + trimmed).
# * test_409_push_active_full_body dies if the gateway checks only
#   `etl_status == active` without ALSO checking `delivery_mode == push` -
#   it would wrongly answer `PULL_NOT_ENABLED` or 202.
