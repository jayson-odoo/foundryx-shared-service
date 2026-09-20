"""Sprint-5/10 S4 coder-added coverage (AC-10-31) - ONE branch the red suite
(`tests/test_s10_s4_gateway_build.py`) leaves unpinned: a task on
``delivery_mode='push'`` that is NOT ``active`` (e.g. still ``draft``).

The red suite pins push+active -> 409 ``PUSH_ACTIVE`` and no-task/pull+draft
-> 409 ``PULL_NOT_ENABLED``, but never a push task that has not been
activated yet. `PullGatewayService.build`'s own branching (``services/
pull_gateway_service.py``) treats this as ``PULL_NOT_ENABLED`` (the book was
never enabled for pull - it is not active PUSH either), never ``PUSH_ACTIVE``
(that code means "the book is now automatic", which requires ``active``).
This file is NEVER edited by a later coder in place of the red suite -
add new cases here instead.
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


def _company(db, connection_id) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="extra coverage key", company_ids=company_ids,
    )
    return plaintext


def test_409_pull_not_enabled_when_task_is_push_but_not_yet_active(client, db):
    """A task saved as push but never activated (draft) is not "now
    automatic" - PUSH_ACTIVE would mislead the consumer into thinking the
    book will silently ignore the request FOREVER; PULL_NOT_ENABLED is the
    honest "not enabled for pull [yet]" code."""
    conn = _connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="draft", delivery_mode="push",
            source_config={
                "connectionId": company.connection_id, "path": "/itembypage",
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
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "PULL_NOT_ENABLED"
