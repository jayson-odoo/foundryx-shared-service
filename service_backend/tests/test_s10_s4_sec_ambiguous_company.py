"""Sprint-5/10 S4 security round 1 - LOW 7: two companies in one tenant
sharing a `sorento_company_code` must never resolve arbitrarily.

PROVEN (independent Opus security review):
`CompanyRepository.get_by_sorento_company_code` has no uniqueness guard and
no `ORDER BY` - the save path (`CompanyService.set_sink_target`) does not
prevent a duplicate code either, so two companies could legitimately end up
sharing one code today, and the gateway would silently pick "the first one
the DB happens to return", non-deterministically.

RED before the fix: the gateway returns 202/200 against ONE of the two
companies rather than refusing.
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


def _connection(db, name):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=name,
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id, database_name, *, sorento_company_code="SRT"):
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
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


def test_two_companies_sharing_a_code_is_a_409_ambiguous_company(client, db):
    conn_a = _connection(db, "db1 REST A")
    conn_b = _connection(db, "db1 REST B")
    company_a = _company(db, conn_a.id, "AED_SORENTO_A")
    company_b = _company(db, conn_b.id, "AED_SORENTO_B")
    for company in (company_a, company_b):
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
    key = _issue_key(db, company_ids=[company_a.id, company_b.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "AMBIGUOUS_COMPANY"
    assert "error" not in body


def test_a_single_matching_company_still_resolves_control(client, db):
    conn = _connection(db, "db1 REST")
    company = _company(db, conn.id, "AED_SORENTO")
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": conn.id, "path": "/itembypage",
                "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
                "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
                "reconcileAt": "02:00", "lookups": [],
            },
        )
    )
    db.commit()
    key = _issue_key(db, company_ids=[company.id])

    response = client.post(
        f"{GATEWAY_PREFIX}/snapshots",
        json={"companyCode": "SRT", "entity": "products"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text
