"""Sprint-5/10 S6 - AC-10-58 security round: the six findings this round
closes, one section each, RED before their fix.

M1  The PUBLIC gateway's `failed` header echoed `snapshot.error` verbatim -
    an internal message built from the source host (`'http://10.13.0.7:8080/
    itembypage' timed out ...`). A third-party key holder must never read the
    deployment's own hostnames/ports back out of it; the OPERATOR header and
    `integration_activity` keep the verbatim text.
M2  No outbound-egress guard on an `autocount` connection's `baseUrl`: an
    operator (or anyone who can reach the connection form) could aim the
    whole paged walk at `169.254.169.254` or a loopback admin port. The
    house guard (`app/services/url_guard.assert_deliverable`) now runs at
    SAVE and again immediately before every request, with the ONE
    development carve-out for a local wrapper.
L1  `PullSnapshotRepository.expired_ids` swept `building` rows too - a row
    carrying a stale `expires_at` could be pruned out from under a live
    build.
L2  `PullSnapshotRepository.delete` took a bare snapshot id (no tenant) -
    the house rule is that every repository query is tenant-scoped.
L4  An audit-write failure inside the router's `except PullGatewayError`
    branch escaped the whole try statement (an exception raised INSIDE an
    except block is not caught by a later `except Exception` of the same
    try), turning a clean flat 404/403/429 into an unhandled error.
L5  `PullKeyService.resolve` stamped `last_used_at` BEFORE the gateway's
    `_service_enabled` gate - so a suspended tenant's / deactivated
    module's key still recorded usage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

GATEWAY_PREFIX = "/api/v1/autocount"
PUBLIC_BASE_URL = "https://autocount.example.invalid/api"
METADATA_BASE_URL = "http://169.254.169.254/latest/meta-data"
LOOPBACK_BASE_URL = "http://127.0.0.1:8001/api"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network."""
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


def _production(monkeypatch) -> None:
    """The dev carve-out OFF - the posture every deployed environment runs."""
    monkeypatch.setattr(settings, "environment", "production")


def _development(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")


def _connection(db, *, base_url: str = PUBLIC_BASE_URL) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": base_url, "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, code: str = "SRT") -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id,
        database_name="AED_SORENTO", company_name="Sorento", name="Sorento",
        is_active=True, sorento_company_code=code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _task(db, company) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
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


def _issue_key(db, *, company_ids) -> str:
    from modules.autocount.services.pull_key_service import PullKeyService

    _row, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="S6 security fixes key", company_ids=company_ids,
    )
    return plaintext


def _login_headers(client) -> Dict[str, str]:
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── M1: the gateway's failed-header message is a FIXED sentence per code ────

# The real shape of a stored error today (live replay, db2): it names the
# source host and port this deployment talks to.
INTERNAL_ERROR_TEXT = (
    "'/itembypage' on http://10.13.0.7:8080 timed out repeatedly even after "
    "2 halving(s) of the page size."
)


def _failed_snapshot(db, company, *, error_code: str, error: str = INTERNAL_ERROR_TEXT):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    return service.stamp_failed(DEFAULT_TENANT_ID, snap, error=error, error_code=error_code)


def test_gateway_failed_header_never_echoes_the_internal_error_text(db):
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header
    from modules.autocount.sync import ERROR_CODE_SOURCE_PAGE_FAILED

    conn = _connection(db)
    company = _company(db, conn.id)
    snapshot = _failed_snapshot(db, company, error_code=ERROR_CODE_SOURCE_PAGE_FAILED)

    header = gateway_snapshot_header(snapshot)
    assert header["error"]["code"] == ERROR_CODE_SOURCE_PAGE_FAILED
    message = header["error"]["message"]
    assert "10.13.0.7" not in message and "8080" not in message, (
        f"the gateway header echoed the internal error text to a third-party "
        f"key holder: {message!r}"
    )
    assert message and message != snapshot.error


def test_operator_header_keeps_the_verbatim_error(db):
    """The fix must be gateway-LOCAL: the operator surface (and the run
    activity behind it) is exactly where the host/port detail belongs."""
    from modules.autocount.services.pull_service import snapshot_header
    from modules.autocount.sync import ERROR_CODE_SOURCE_PAGE_FAILED

    conn = _connection(db)
    company = _company(db, conn.id)
    snapshot = _failed_snapshot(db, company, error_code=ERROR_CODE_SOURCE_PAGE_FAILED)

    header = snapshot_header(snapshot)
    assert header["error"] == {
        "code": ERROR_CODE_SOURCE_PAGE_FAILED,
        "message": INTERNAL_ERROR_TEXT,
    }


def test_every_pinned_failed_code_has_its_own_fixed_sentence(db):
    """Drift guard: a new member of ``PULL_SNAPSHOT_FAILED_CODES`` without a
    sentence would silently fall back to the generic one."""
    from modules.autocount.services.pull_gateway_service import (
        GATEWAY_FAILED_MESSAGES,
        gateway_snapshot_header,
    )
    from modules.autocount.sync import PULL_SNAPSHOT_FAILED_CODES

    missing = [c for c in PULL_SNAPSHOT_FAILED_CODES if c not in GATEWAY_FAILED_MESSAGES]
    assert missing == [], f"no operator-safe gateway sentence for: {missing}"

    conn = _connection(db)
    company = _company(db, conn.id)
    for code in PULL_SNAPSHOT_FAILED_CODES:
        snapshot = _failed_snapshot(db, company, error_code=code)
        header = gateway_snapshot_header(snapshot)
        assert header["error"]["message"] == GATEWAY_FAILED_MESSAGES[code]


def test_an_unknown_or_missing_error_code_falls_back_to_the_generic_sentence(db):
    from modules.autocount.services.pull_gateway_service import (
        GATEWAY_FAILED_FALLBACK_MESSAGE,
        gateway_snapshot_header,
    )

    conn = _connection(db)
    company = _company(db, conn.id)
    snapshot = _failed_snapshot(db, company, error_code="SOMETHING_NEW")

    header = gateway_snapshot_header(snapshot)
    assert header["error"]["message"] == GATEWAY_FAILED_FALLBACK_MESSAGE


# ── M2: the outbound egress guard on `baseUrl` ──────────────────────────────


AUTOCOUNT_OPEN_PAYLOAD = {
    "provider": "autocount",
    "name": "S6 egress guard",
    "config": {"auth": "none", "baseUrl": PUBLIC_BASE_URL},
    "credentials": {},
}


def _save_connection(client, base_url: str):
    headers = _login_headers(client)
    payload = {
        **AUTOCOUNT_OPEN_PAYLOAD,
        "config": {**AUTOCOUNT_OPEN_PAYLOAD["config"], "baseUrl": base_url},
    }
    return client.post("/integrations/connections", json=payload, headers=headers)


@pytest.mark.parametrize("base_url", [METADATA_BASE_URL, LOOPBACK_BASE_URL])
def test_an_internal_base_url_is_refused_at_save(client, monkeypatch, base_url):
    _production(monkeypatch)
    res = _save_connection(client, base_url)
    assert res.status_code == 422, res.text
    assert "baseurl" in res.json()["detail"].lower()


def test_a_public_https_base_url_still_saves(client, monkeypatch):
    """CONTROL: the guard must refuse internal targets only."""
    _production(monkeypatch)
    res = _save_connection(client, PUBLIC_BASE_URL)
    assert res.status_code in (200, 201), res.text


def test_the_development_carve_out_allows_a_local_wrapper_at_save(client, monkeypatch):
    """BL-SS-166's precedent shape (a settings-flag carve-out, development
    only): `http://localhost:PORT` has to keep working for live-verify."""
    _development(monkeypatch)
    res = _save_connection(client, LOOPBACK_BASE_URL)
    assert res.status_code in (200, 201), res.text


def test_the_development_carve_out_does_not_extend_to_a_metadata_ip(client, monkeypatch):
    """The carve-out is LOOPBACK only - a cloud metadata address is never a
    local development target, so it stays refused even in development."""
    _development(monkeypatch)
    res = _save_connection(client, METADATA_BASE_URL)
    assert res.status_code == 422, res.text
    assert "baseurl" in res.json()["detail"].lower()


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _walk(db, conn, *, calls: List[httpx.Request]):
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource
    import modules.autocount.http_source.source as source_module

    company = _company(db, conn.id)
    config = _task(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1, "TotalPages": 1,
                  "Data": [{"ItemCode": "A1"}]},
        )

    original = source_module.HttpApiClient
    source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(
        base_url, transport=httpx.Client(transport=httpx.MockTransport(handler))
    )
    try:
        source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
        source.fetch_changes(Watermark())
    finally:
        source_module.HttpApiClient = original


def test_a_walk_against_an_internal_base_url_is_refused_before_any_request(db, monkeypatch):
    """The stored connection is the attacker-controlled input here (DNS can
    also be re-pointed after save), so the guard re-runs at request time -
    a named failure, and the transport is never touched at all."""
    from modules.autocount.http_source.errors import HttpSourceError

    _production(monkeypatch)
    conn = _connection(db, base_url=METADATA_BASE_URL)
    calls: List[httpx.Request] = []

    with pytest.raises(HttpSourceError) as excinfo:
        _walk(db, conn, calls=calls)

    assert calls == [], "a blocked target still reached the HTTP transport"
    assert "baseurl" in str(excinfo.value).lower()


def test_the_development_carve_out_lets_a_local_walk_through(db, monkeypatch):
    """CONTROL for the guard: under the carve-out the SAME walk reaches the
    transport (so the guard is what refuses above, not some other error)."""
    _development(monkeypatch)
    conn = _connection(db, base_url=LOOPBACK_BASE_URL)
    calls: List[httpx.Request] = []

    _walk(db, conn, calls=calls)

    assert calls, "the development carve-out did not let a local wrapper through"


# ── L1/L2: pruning is tenant-scoped and never touches a live build ──────────


def _expired_snapshot(db, company, *, status: str):
    """A row already past its `expires_at`. A `building` row only ever
    carries one when a previous attempt on the same row stamped it."""
    from modules.autocount.models import AcPullSnapshot
    from modules.autocount.services.pull_service import SnapshotService

    now = datetime.now(timezone.utc)
    snap = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="gateway",
    )
    row = db.query(AcPullSnapshot).filter(AcPullSnapshot.id == snap.id).one()
    row.status = status
    row.expires_at = now - timedelta(hours=1)
    db.commit()
    return row


def test_pruning_never_deletes_a_snapshot_that_is_still_building(db):
    from modules.autocount.models import AcPullSnapshot, PULL_SNAPSHOT_STATUS_BUILDING
    from modules.autocount.services.pull_service import prune_pull_snapshots

    conn = _connection(db)
    company = _company(db, conn.id)
    building = _expired_snapshot(db, company, status=PULL_SNAPSHOT_STATUS_BUILDING)

    prune_pull_snapshots(db)

    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.id == building.id).first() is not None, (
        "an expired-dated snapshot that is still BUILDING was pruned out "
        "from under its own job"
    )


def test_pruning_does_delete_an_expired_ready_snapshot_control(db):
    from modules.autocount.models import AcPullSnapshot, PULL_SNAPSHOT_STATUS_READY
    from modules.autocount.services.pull_service import prune_pull_snapshots

    conn = _connection(db)
    company = _company(db, conn.id)
    ready = _expired_snapshot(db, company, status=PULL_SNAPSHOT_STATUS_READY)

    result = prune_pull_snapshots(db)

    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.id == ready.id).first() is None
    assert result["expired"] == 1


def test_snapshot_delete_is_a_no_op_for_the_wrong_tenant(db):
    from modules.autocount.models import AcPullSnapshot, PULL_SNAPSHOT_STATUS_READY
    from modules.autocount.repositories import PullSnapshotRepository

    conn = _connection(db)
    company = _company(db, conn.id)
    ready = _expired_snapshot(db, company, status=PULL_SNAPSHOT_STATUS_READY)

    PullSnapshotRepository(db).delete("some-other-tenant", ready.id)
    db.commit()

    assert db.query(AcPullSnapshot).filter(AcPullSnapshot.id == ready.id).first() is not None, (
        "a snapshot was deleted with a tenant id that does not own it"
    )


# ── L4: an audit-write failure never breaks the response ────────────────────


def test_an_audit_failure_inside_the_error_path_still_renders_the_flat_body(
    client, db, monkeypatch
):
    from modules.autocount.routers import pull_v1

    conn = _connection(db)
    company = _company(db, conn.id)
    _task(db, company)
    key = _issue_key(db, company_ids=[company.id])

    def _boom(*args, **kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(pull_v1, "write_pull_audit", _boom)

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "NOPE", "entity": "products"},
        headers={"X-API-Key": key},
    )

    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "UNKNOWN_COMPANY"
    assert "error" not in body
    assert body["companyCode"] == "NOPE"


# ── L5: `last_used_at` is stamped only once the service gate passes ─────────


def test_a_key_is_not_stamped_when_the_service_gate_refuses(client, db):
    from app.services.app_store_service import AppStoreService
    from modules.autocount.models import AcPullApiKey

    conn = _connection(db)
    company = _company(db, conn.id)
    _task(db, company)
    key = _issue_key(db, company_ids=[company.id])
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "autocount")

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 403, response.text

    row = db.query(AcPullApiKey).filter(AcPullApiKey.tenant_id == DEFAULT_TENANT_ID).one()
    db.refresh(row)
    assert row.last_used_at is None, (
        "the key was stamped as used even though the gateway refused the "
        "call at the service gate"
    )


def test_a_key_is_stamped_when_the_service_gate_passes_control(client, db):
    from modules.autocount.models import AcPullApiKey

    conn = _connection(db)
    company = _company(db, conn.id)
    _task(db, company)
    key = _issue_key(db, company_ids=[company.id])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist",
        headers={"X-API-Key": key},
    )
    assert response.status_code == 404, response.text

    row = db.query(AcPullApiKey).filter(AcPullApiKey.tenant_id == DEFAULT_TENANT_ID).one()
    db.refresh(row)
    assert row.last_used_at is not None


# ── nit: the pull permission descriptions name what they actually gate ──────


def test_the_pull_read_permission_description_names_snapshots() -> None:
    import csv
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "modules/autocount/permissions/permissions.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows: List[Dict[str, Any]] = list(csv.DictReader(handle))
    read_row = next(
        r for r in rows if r["resource"] == "autocount.pull" and r["action"] == "read"
    )
    assert read_row["description"] == "View human-invoked pull snapshots"
