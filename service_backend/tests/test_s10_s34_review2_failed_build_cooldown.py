"""Sprint-5/10 S3+S4 review round 2 - MUST-FIX 3 (item 3, AC-10-26): the
build cooldown keys on ``extracted_at``, which ``SnapshotService.stamp_failed``
never sets - a snapshot that just FAILED has ``extracted_at is None``, so
``PullService.request_build``'s own cooldown check (``existing.extracted_at
is not None``) was silently skipped entirely, letting a caller hammer a
consistently-failing extraction (e.g. a misconfigured task) at unlimited
rate. The fix keys the cooldown on ``existing.extracted_at or
existing.created_at`` - a READY snapshot's own explicit build-end timestamp
still wins exactly as before (never regressing
``test_s10_s3_snapshot_build_job.py``'s own cooldown pair, which controls
``extracted_at`` directly), while a FAILED snapshot (no ``extracted_at``)
now falls back to its ``created_at`` (the moment the failed attempt itself
was made) - so at most one build attempt per 60s applies uniformly,
regardless of outcome.

RED before the fix: a build request placed immediately after a FAILED
build for the same triple is not refused at all (the cooldown branch is
skipped because ``extracted_at is None``), so this file's own "10 seconds
after a failure" test currently starts a second extraction outright.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    PULL_SNAPSHOT_STATUS_FAILED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


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


def _product_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True, sort_order=0,
        )
    )
    db.commit()
    db.refresh(config)
    return config


def _failed_snapshot_created_at(db, company, *, created_at):
    from modules.autocount.services.pull_service import SnapshotService

    service = SnapshotService(db)
    snap = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.stamp_failed(
        DEFAULT_TENANT_ID, snap, error="Source page 2 failed.", error_code="SOURCE_PAGE_FAILED",
    )
    snap.created_at = created_at
    db.add(snap)
    db.commit()
    db.refresh(snap)
    assert snap.status == PULL_SNAPSHOT_STATUS_FAILED
    assert snap.extracted_at is None, "control: a failed snapshot never carries extracted_at"
    return snap


def _stub_ok_transport(monkeypatch) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                  "Data": [{"ItemCode": "A1"}]},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )


def test_a_build_10s_after_a_failed_build_is_refused_with_retry_after(db):
    from modules.autocount.services.pull_service import PullBuildCooldownError, PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    _failed_snapshot_created_at(db, company, created_at=NOW - timedelta(seconds=10))

    with pytest.raises(PullBuildCooldownError) as exc_info:
        PullService(db).request_build(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
        )
    assert 0 < exc_info.value.retry_after_seconds <= 50


def test_a_build_60s_after_a_failed_build_is_allowed(db, monkeypatch):
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    failed = _failed_snapshot_created_at(db, company, created_at=NOW - timedelta(seconds=61))
    _stub_ok_transport(monkeypatch)

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    assert result.id != failed.id
    assert result.status == "ready"


def test_reattach_to_an_in_flight_build_still_wins_over_the_cooldown(db):
    """A ``building`` snapshot created WELL inside the cooldown window must
    still be re-attached to (never refused) - the re-attach branch runs
    BEFORE the cooldown check, and this must survive the item-3 fix
    unchanged."""
    from modules.autocount.services.pull_service import PullService, SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    in_flight = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    in_flight.created_at = NOW - timedelta(seconds=5)
    db.add(in_flight)
    db.commit()

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    assert result.id == in_flight.id
