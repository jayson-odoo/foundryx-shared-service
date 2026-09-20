"""Sprint-5/10 S4 security round 1 - MEDIUM 6: `Cache-Control: no-store` on
every gateway response, success AND error - this surface serves a
customer's ERP master data behind a bearer-style key; nothing on it should
ever be cacheable by an intermediary.

RED before the fix: no route sets the header at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

GATEWAY_PREFIX = "/api/v1/autocount"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
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


def _company(db, *, sorento_company_code="SRT") -> AcCompany:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_SORENTO",
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
        DEFAULT_TENANT_ID, name="k", company_ids=company_ids,
    )
    return plaintext


def _ready_snapshot(db, company):
    from modules.autocount.services.pull_service import SnapshotService

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


def test_a_successful_header_read_carries_no_store(client, db):
    company = _company(db)
    snap = _ready_snapshot(db, company)
    key = _issue_key(db, company_ids=[company.id])

    response = client.get(f"{GATEWAY_PREFIX}/snapshots/{snap.id}", headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"


def test_a_successful_rows_read_carries_no_store(client, db):
    company = _company(db)
    snap = _ready_snapshot(db, company)
    key = _issue_key(db, company_ids=[company.id])

    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/{snap.id}/rows", headers={"X-API-Key": key},
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"


def test_a_401_error_carries_no_store(client):
    response = client.get(f"{GATEWAY_PREFIX}/snapshots/does-not-exist")
    assert response.status_code == 401, response.text
    assert response.headers.get("cache-control") == "no-store"


def test_a_404_error_carries_no_store(client, db):
    company = _company(db)
    key = _issue_key(db, company_ids=[company.id])
    response = client.get(
        f"{GATEWAY_PREFIX}/snapshots/does-not-exist", headers={"X-API-Key": key},
    )
    assert response.status_code == 404, response.text
    assert response.headers.get("cache-control") == "no-store"
