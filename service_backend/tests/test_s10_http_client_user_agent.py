"""Sprint-5/10 S1 - AC-10-08: an explicit, honest ``User-Agent`` on every
open-REST request. Cloudflare 403s the default python-urllib UA, and the
default httpx UA (``python-httpx/<version>``) is not something to depend on
either - both are exactly what this test rejects.

RED before the coder: today ``HttpApiClient.get`` sends only
``{"Accept": "application/json"}`` (``modules/autocount/http_source/
client.py``), so httpx fills in ITS OWN default ``User-Agent`` header - this
test fails on a real, honest assertion (the header does not start with the
required prefix), never an ImportError.

Assumed name (not fixed by the plan beyond "an explicit, honest User-Agent
(``Foundryx-AutoCount-ESB/<module version>``)"): the exact VERSION suffix is
intentionally NOT pinned here (the module's ``manifest.json`` version is
"0.10.0" today and S1's own files list does not bump it - only the later
pull-gateway slice does) - only the fixed, honest PREFIX is pinned, so a
version bump elsewhere in this plan can never turn this test red for the
wrong reason.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.client import HttpApiClient
from modules.autocount.http_source.source import HttpApiSource

BASE_URL = "https://hapi.sorento.cc.cd/api/db2"
UA_PREFIX = "Foundryx-AutoCount-ESB/"


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_client_sends_explicit_user_agent_never_the_httpx_default():
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"Location": "A1"}])

    client = HttpApiClient(BASE_URL, transport=_transport(handler))
    client.get("/location", {"page": 1, "pageSize": 50})
    ua = calls[0].headers.get("user-agent", "")
    assert ua.startswith(UA_PREFIX), f"got {ua!r}"
    assert "python-httpx" not in ua.lower()
    assert "urllib" not in ua.lower()
    # AC-10-08 is explicit "alongside Accept: application/json" - the
    # existing header must survive, not be replaced.
    assert calls[0].headers.get("accept") == "application/json"


def test_user_agent_present_on_every_page_of_a_multi_page_walk():
    # Two pages of the SAME endpoint - the header must not be a one-shot
    # fluke on the first request only.
    calls: List[httpx.Request] = []
    pages = [
        {"TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2, "Data": [{"Location": "A1"}]},
        {"TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2, "Data": [{"Location": "A2"}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page - 1])

    client = HttpApiClient(BASE_URL, transport=_transport(handler))
    client.get("/location", {"page": 1, "pageSize": 1})
    client.get("/location", {"page": 2, "pageSize": 1})
    assert len(calls) == 2
    for call in calls:
        assert call.headers.get("user-agent", "").startswith(UA_PREFIX)


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    yield db, company, conn
    db.close()


def test_user_agent_present_on_lookup_endpoint_requests_too(rig):
    """AC-10-08 says "on every request" - the lookup endpoint (AC-10-02) is
    not a second, forgotten client."""
    db, company, conn = rig
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [
                {
                    "path": "/itemuombypage", "as": "uom",
                    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
                    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
                }
            ],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/itemuombypage"):
            return httpx.Response(
                200,
                json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
            )
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                  "Data": [{"ItemCode": "SRT-01", "LastModified": "2026-08-01T09:00:00"}]},
        )

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT, transport=_transport(handler))
    source.fetch_changes(Watermark())
    assert len(calls) == 2, "expected one main-path request and one lookup request"
    for call in calls:
        assert call.headers.get("user-agent", "").startswith(UA_PREFIX), call.url


# KILL TEST (for the reviewer): delete the coder's UA header line entirely -
# every test in this file goes red (they all assert the prefix); reverting
# ONLY the lookup-side wiring (e.g. building a second, header-less
# HttpApiClient for lookup endpoints) flips
# ``test_user_agent_present_on_lookup_endpoint_requests_too`` alone.
