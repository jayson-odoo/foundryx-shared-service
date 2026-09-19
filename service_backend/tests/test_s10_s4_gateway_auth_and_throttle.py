"""Sprint-5/10 S4 - the public gateway's auth + throttle: AC-10-30, 35.

Appendix A2: `X-API-Key` header, tenancy + the allowed company SET come from
the key row, never the request. Every one of missing/malformed/unknown/
revoked/wrong-tenant gives the SAME uniform 401 - no oracle. Fixture:
`documentation/plans/sprint-5/10-fixtures/error-401-invalid-api-key.json`.

RED before the coder: `/api/v1/autocount/*` does not exist at all yet -
every request 404s at the FastAPI routing level (no matching route), which
IS the "missing feature" RED (never a bare `assert False`).

ASSUMED NAMES:

* Manifest router entry `{"name": "pull_v1", "prefix": "/api/v1/autocount",
  "public": true}` (mirrors omnichannel's own `api_v1` entry - `"public":
  true` skips the session/module gate the loader injects everywhere else,
  `app/module_loader.py:59/88`).
* `modules/autocount/pull_auth.py::get_pull_api_key` - a FastAPI dependency
  resolving `X-API-Key` to `(tenant_id, key_id, company_ids)` via
  `PullKeyService.resolve`; raises a gateway error (401 `INVALID_API_KEY`)
  for missing/malformed/unknown/revoked, uniformly - same status AND body
  for all four, no timing-observable branch. 403 `SERVICE_NOT_ENABLED` when
  the `autocount` module is inactive for the key's tenant OR the tenant is
  suspended/archived (the SAME `Status.blocks_access`/`is_archived` +
  `ModuleRepository.is_active` predicate `scheduler.sweep_etl_tasks` uses).
* `app/models/auth_throttle.py::THROTTLE_SCOPE_PULL = "pull"`;
  `app/config.py`: `throttle_pull_max_fails`, `throttle_pull_window_minutes`
  (mirrors `throttle_embed_*`/`throttle_webchat_*`).
  `app/services/throttle.py::ThrottleService.enforce_pull(ip=...)` /
  `.record_pull_failure(ip=...)` - enforced BEFORE key resolution; a 401
  records a failure; a successful resolve never does.
* Every gateway response body is the flat Appendix A shape
  `{"code","message","companyCode","entity"}` - `companyCode`/`entity` are
  populated from the REQUEST BODY on `POST /snapshots` (always available)
  but are genuinely UNKNOWABLE before key resolution on the two GET routes
  (nothing in the URL names them) - flagged as an ambiguity in the final
  report, not silently assumed. This file only asserts `code`+`message`
  strictly on the GET routes' 401s; `POST /snapshots`'s full-body 401 is
  pinned in `test_s10_s4_gateway_build.py`.

Kill-test notes are per section below.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.tenant import Tenant
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig

OTHER_TENANT = "tenant-other-s10-s4-gw-auth"
GATEWAY_PREFIX = "/api/v1/autocount"


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


def _company(db, *, tenant_id=DEFAULT_TENANT_ID, sorento_company_code="SRT") -> AcCompany:
    from app.models.connection import Connection

    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _pull_task(db, company, *, tenant_id=DEFAULT_TENANT_ID) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=tenant_id, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status="active", delivery_mode="pull",
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


def _issue_key(db, *, tenant_id=DEFAULT_TENANT_ID, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        tenant_id, name="gateway test key", company_ids=company_ids,
    )
    return plaintext


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s10-s4-gw-auth", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


# ── AC-10-30: uniform 401, no oracle ─────────────────────────────────────────


def test_missing_key_header_is_401_invalid_api_key(client):
    response = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist")
    assert response.status_code == 401, response.text
    body = response.json()
    assert body["code"] == "INVALID_API_KEY"


def test_malformed_key_is_401_same_shape_as_missing(client):
    missing = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist")
    malformed = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist",
        headers={"X-API-Key": "not-even-the-right-scheme"},
    )
    assert malformed.status_code == missing.status_code == 401
    assert malformed.json() == missing.json()


def test_unknown_key_is_401_same_shape_as_missing(client):
    missing = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist")
    unknown = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist",
        headers={"X-API-Key": "fxa_live_" + "x" * 43},
    )
    assert unknown.status_code == missing.status_code == 401
    assert unknown.json() == missing.json()


def test_revoked_key_is_401_same_shape_as_missing(client, db):
    from modules.autocount.services.pull_key_service import PullKeyService

    company = _company(db)
    service = PullKeyService(db)
    key, plaintext = service.issue(DEFAULT_TENANT_ID, name="k", company_ids=[company.id])
    service.revoke(DEFAULT_TENANT_ID, key.id)

    missing = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist")
    revoked = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers={"X-API-Key": plaintext},
    )
    assert revoked.status_code == missing.status_code == 401
    assert revoked.json() == missing.json()


def test_a_valid_key_used_for_a_different_tenants_snapshot_reads_uniform_404_not_401(
    client, db,
):
    """A VALID key (its own tenant) probing a snapshot id from ANOTHER
    tenant must read as 404 UNKNOWN_SNAPSHOT (AC-10-30's own cross-tenant
    test), never 401 - the key resolved fine; the snapshot simply is not in
    its scope. Distinct from the four 401 cases above by construction."""
    _other_tenant(db)
    their_company = _company(db, tenant_id=OTHER_TENANT, sorento_company_code="MCH")
    from modules.autocount.services.pull_service import SnapshotService

    snap = SnapshotService(db).create_building(
        OTHER_TENANT, their_company.id, ENTITY_PRODUCT,
        company_code=their_company.sorento_company_code, requested_via="gateway",
    )

    my_company = _company(db, sorento_company_code="SRT")
    my_key = _issue_key(db, company_ids=[my_company.id])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": my_key},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "UNKNOWN_SNAPSHOT"


# ── AC-10-35: the pull throttle scope ─────────────────────────────────────────


def test_throttle_scope_pull_is_registered():
    from app.models.auth_throttle import THROTTLE_SCOPE_PULL

    assert THROTTLE_SCOPE_PULL == "pull"


def test_settings_carry_the_two_pull_throttle_knobs():
    from app.config import settings

    assert hasattr(settings, "throttle_pull_max_fails")
    assert hasattr(settings, "throttle_pull_window_minutes")


def test_repeated_401s_from_the_same_ip_eventually_429(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_pull_max_fails", 2)
    unauthed = {"X-API-Key": "fxa_live_" + "y" * 43}
    first = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers=unauthed)
    second = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers=unauthed)
    assert first.status_code == second.status_code == 401
    third = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers=unauthed)
    assert third.status_code == 429, third.text
    assert third.headers.get("Retry-After")


def test_a_successful_call_never_consumes_the_pull_throttle_bucket(client, db, monkeypatch):
    """CONTROL: enough SUCCESSFUL calls to exceed the same numeric limit a
    401 would trip must NOT throttle - proves the bucket only counts
    failures, never merely traffic."""
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_pull_max_fails", 2)
    company = _company(db)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])
    headers = {"X-API-Key": key}

    for _ in range(5):
        response = client.post(
            f"{GATEWAY_PREFIX}/snapshots",
            json={"companyCode": "SRT", "entity": "products"},
            headers=headers,
        )
        assert response.status_code in (200, 202), response.text


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_malformed_key_is_401_same_shape_as_missing /
#   test_unknown_key_is_401_same_shape_as_missing /
#   test_revoked_key_is_401_same_shape_as_missing die if any ONE of the four
#   failure classes takes a different code path (e.g. a malformed key
#   raising a 422 from an implicit length/regex validator instead of the
#   uniform 401) - each is compared BYTE FOR BYTE against the same-request
#   "missing key" baseline, not against a hardcoded literal that could drift
#   from what the OTHER three actually return.
# * test_a_valid_key_used_for_a_different_tenants_snapshot_reads_uniform_404_not_401
#   dies if the gateway resolves a snapshot id with an unscoped `get_by_id`
#   (the polymorphic-id leak class) - it would 200, not 404.
# * test_a_successful_call_never_consumes_the_pull_throttle_bucket dies if
#   the throttle records EVERY call (traffic-based) rather than failures
#   only - it would 429 on the 3rd successful call under this fixture's
#   `max_fails=2`.
