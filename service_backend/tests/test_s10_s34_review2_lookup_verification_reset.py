"""Sprint-5/10 S3+S4 review round 2 - nit (item 6): ``HttpApiSource.
_lookup_verification`` is populated by ``_apply_lookups`` but never reset -
an instance REUSED across two ``fetch_changes`` calls (the sql_db preview
seam and, more generally, any future caller that keeps one instance across
calls) would carry stale entries from the FIRST call into the SECOND one's
``FetchResult.lookup_verification``, even for a lookup whose alias no
longer exists on the second call's config.

RED before the fix: the second ``fetch_changes`` call's own
``lookup_verification`` still contains the FIRST call's alias entry even
though the second call's ``self.lookups`` no longer names it.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

DB_NAME = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"


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


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Sorento", name="Sorento", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config_with_lookup(db, company, connection_id: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [
                {
                    "path": "/uom",
                    "as": "uom",
                    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
                    "fields": [{"remote": "UOM", "as": "LookupUOM"}],
                },
            ],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _ok_page(rows) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": len(rows) or 1, "TotalPages": 1, "Data": rows}


def test_lookup_verification_never_carries_stale_entries_across_calls(db, monkeypatch):
    """Two consecutive ``fetch_changes`` calls on the SAME ``HttpApiSource``
    instance - the second must report ONLY what the second call's own walk
    actually verified, never a leftover alias from the first."""
    from modules.autocount.http_source.source import HttpApiSource

    conn = _connection(db)
    company = _company(db, conn.id)
    config = _config_with_lookup(db, company, conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "UOM": "PCS"}]))

    monkeypatch.setattr(
        "modules.autocount.http_source.source.HttpApiClient",
        lambda base_url, **kw: __import__(
            "modules.autocount.http_source.client", fromlist=["HttpApiClient"]
        ).HttpApiClient(base_url, transport=httpx.Client(transport=httpx.MockTransport(handler))),
    )

    source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
    first = source.fetch_changes(Watermark())
    assert "uom" in first.lookup_verification

    # Second call: wipe the configured lookups out from under the SAME
    # instance (simulates a config that no longer names any lookup) - the
    # fresh result must carry NO alias at all, not the first call's.
    source.lookups = []
    second = source.fetch_changes(Watermark())
    assert second.lookup_verification == {}, (
        f"stale entry survived into the second call: {second.lookup_verification}"
    )
