"""Sprint-5/10 S3+S4 review round 2 - MUST-FIX 2 (item 2, AC-10-32/A7):
``sourcePageSize`` is always ``null`` today because nobody ever writes the
metadata key both the operator (``pull_service.snapshot_header``) and
gateway (``pull_gateway_service.gateway_snapshot_header``) headers already
READ. ``HttpApiSource`` now exposes the effective page size the MAIN walk
settled on (post any AC-10-75 halving) as a read-only ``source_page_size``
attribute, ``sync._run_pull_snapshot`` records it into the snapshot's own
``metadata_json``, and both headers serve it - subject to the SAME
per-status omission rules every other ``ready``-only key already follows.

RED before the fix: ``HttpApiSource`` has no ``source_page_size`` attribute
at all (``AttributeError``), and a ``ready`` header's ``sourcePageSize`` is
always ``None`` even though a build genuinely walked at 1000 (or a halved
500).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"
NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Backoff must never actually sleep in the test suite (mirrors
    ``test_s10_http_retry.py``'s own copy of this fixture)."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


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


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


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
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    yield db, company, conn
    db.close()


def _config(db, company, connection_id: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
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


# ── HttpApiSource.source_page_size (unit level) ──────────────────────────────


def test_source_page_size_defaults_to_1000_on_a_clean_walk(rig, monkeypatch):
    from modules.autocount.http_source.source import HttpApiSource

    db, company, conn = rig
    config = _config(db, company, conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

    monkeypatch.setattr(
        "modules.autocount.http_source.source.HttpApiClient",
        lambda base_url, **kw: __import__(
            "modules.autocount.http_source.client", fromlist=["HttpApiClient"]
        ).HttpApiClient(base_url, transport=_transport(handler)),
    )
    source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
    assert source.source_page_size is None, "unset before any walk has run"
    source.fetch_changes(Watermark())
    assert source.source_page_size == 1000


def test_source_page_size_reflects_a_halved_size_after_two_timeouts(rig, monkeypatch):
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource

    db, company, conn = rig
    config = _config(db, company, conn.id)

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page_size = request.url.params.get("pageSize")
        if page_size == "1000":
            # Two timeouts at the ORIGINAL size force exactly one halving.
            return httpx.Response(524, json={})
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

    monkeypatch.setattr(
        "modules.autocount.http_source.source.HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=_transport(handler)),
    )
    source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
    source.fetch_changes(Watermark())
    assert source.source_page_size == 500
    served_sizes = {c.url.params.get("pageSize") for c in calls}
    assert "500" in served_sizes


# ── snapshot header (operator + gateway) omission rules ──────────────────────


def _building_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID):
    from modules.autocount.services.pull_service import SnapshotService

    return SnapshotService(db).create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )


def _failed_snapshot(db, company, *, tenant_id=DEFAULT_TENANT_ID):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        tenant_id, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    return service.stamp_failed(
        tenant_id, snap, error="Source page 2 failed.", error_code="SOURCE_PAGE_FAILED",
    )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db) -> AcCompany:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def test_a_real_build_records_source_page_size_onto_the_ready_snapshot(db, monkeypatch):
    """End-to-end, driven at the ``PullService.request_build`` seam (mirrors
    ``test_s10_s3_snapshot_build_job.py``'s own choice): the ACTUAL walk uses
    the default 1000 page size, and that value must land on the snapshot's
    own ``metadata_json`` (never a hand-injected fixture value), so both
    headers can serve it. This is the genuine RED: today NOTHING writes this
    key during a real build, so ``sourcePageSize`` stays ``None`` even though
    the walk plainly used 1000."""
    from modules.autocount.models import AcEntityConfig, AcFieldMapping
    from modules.autocount.services.pull_service import PullService, snapshot_header

    company = _company(db)
    conn_id = company.connection_id
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status="active", delivery_mode="pull",
            source_config={
                "connectionId": conn_id, "path": "/itembypage", "keyFields": ["ItemCode"],
                "watermarkField": None, "comparedFields": [], "distinctOf": None,
                "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
                "lookups": [],
            },
        )
    )
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True, sort_order=0,
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

    monkeypatch.setattr(
        "modules.autocount.http_source.source.HttpApiClient",
        lambda base_url, **kw: __import__(
            "modules.autocount.http_source.client", fromlist=["HttpApiClient"]
        ).HttpApiClient(base_url, transport=_transport(handler)),
    )

    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)
    assert snapshot.status == "ready", snapshot.error
    assert snapshot.metadata_json.get("sourcePageSize") == 1000
    assert snapshot_header(snapshot)["sourcePageSize"] == 1000


def test_operator_building_header_omits_source_page_size(db):
    from modules.autocount.services.pull_service import snapshot_header

    company = _company(db)
    snap = _building_snapshot(db, company)
    header = snapshot_header(snap)
    # The operator header shape always carries the key (defaulted null) for
    # non-failed states per its own dict-comprehension shape below the
    # `ready`-only counters - but the value itself must never be a fabricated
    # number while building.
    assert header.get("sourcePageSize") is None


def test_gateway_building_header_omits_source_page_size_key_entirely(db):
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header

    company = _company(db)
    snap = _building_snapshot(db, company)
    header = gateway_snapshot_header(snap)
    assert "sourcePageSize" not in header


def test_gateway_failed_header_omits_source_page_size_key_entirely(db):
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header

    company = _company(db)
    snap = _failed_snapshot(db, company)
    header = gateway_snapshot_header(snap)
    assert "sourcePageSize" not in header
