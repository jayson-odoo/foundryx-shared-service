"""Sprint-5/10 S3+S4 review round 2 - MUST-FIX 4 (item 4, AC-10-15): a build
on a PUSH-mode-and-active pair must be refused at the SERVICE
(``PullService.request_build``), not only in the public gateway's own route
(``PullGatewayService.build``). Today the OPERATOR route
(``POST /autocount/pull/snapshots``) has no such guard at all and happily
starts a real extraction for a book that has flipped to automatic - the
pull-only invariant (AC-10-15) only held by accident, because the gateway
checked it BEFORE ever calling ``request_build``.

RED before the fix: the operator-route test below observes a REAL build
(status ``ready``) instead of a 409, since ``PullService.request_build``
does not consult ``AcEntityConfig.delivery_mode``/``etl_status`` at all.
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
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
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


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _push_active_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status="active", delivery_mode="push",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="push active test key", company_ids=company_ids,
    )
    return plaintext


# ── the SERVICE itself refuses, at the seam both routes share ───────────────


def test_request_build_raises_push_active_directly(db):
    from modules.autocount.services.pull_service import PullPushActiveError, PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _push_active_task(db, company, conn.id)

    with pytest.raises(PullPushActiveError):
        PullService(db).request_build(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator",
        )


# ── operator route (the actual gap: no guard at all today) ──────────────────


def test_operator_route_refuses_a_push_active_pair_with_409(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _push_active_task(db, company, conn.id)

    headers = _auth(client)
    response = client.post(
        "/autocount/pull/snapshots",
        json={"companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=headers,
    )
    assert response.status_code == 409, response.text

    # Control: no snapshot was ever created for this refused attempt.
    from modules.autocount.models import AcPullSnapshot

    count = (
        db.query(AcPullSnapshot)
        .filter(AcPullSnapshot.company_id == company.id, AcPullSnapshot.entity_type == ENTITY_PRODUCT)
        .count()
    )
    assert count == 0


# ── gateway control: its own existing 409 stays green ────────────────────────


def test_gateway_route_still_refuses_a_push_active_pair_with_409_push_active(client, db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _push_active_task(db, company, conn.id)
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PUSH_ACTIVE"
