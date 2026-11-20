"""Sprint-5/10 S3 review round 1 - kill-test finding (a): the inline
``delivery_mode == push`` gate in the PAGED path (``sync.py``'s old
~L1915, the plain path's twin at old ~L840 already removed) is EQUALLY
dead code, for the SAME reason.

A mutation that dropped either inline gate survived the existing S3 suite
because every pull-mode fixture in ``test_s10_s3_delivery_mode.py`` uses
``source_impl="autocount_http"``, which never dispatches into
``_run_paged_sql_db`` in the first place (only ``SOURCE_IMPL_SQL_DB`` with a
configured ``watermark_column`` does) - so neither gate was ever actually
exercised by a fixture that could reach it. This file uses a
``SOURCE_IMPL_SQL_DB`` pull-mode config (the ONLY source impl that CAN reach
the paged branch) to prove ``run_autocount_sync``'s own top-of-function pull
short-circuit (AC-10-12/13) alone decides the outcome: ``source_factory`` is
never even called, ``_run_paged_sql_db`` is never called, ``auto_push`` is
never called, nothing is staged - so BOTH inline gates were always
unreachable and the removal is safe.

RED before the fix (proven by reasoning, matching the coordinator's own
kill-test note): before the pull short-circuit existed at all (pre-dating
this plan), a ``SOURCE_IMPL_SQL_DB`` pull-mode config with a
``watermark_column`` WOULD have reached ``source_factory``/
``_run_paged_sql_db`` - this test's own spies would have recorded calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    DELIVERY_MODE_PULL,
    ETL_STATUS_ACTIVE,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
)

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20). Review round 2 nit (item 6) -
    this file makes no HTTP call of its own (``sql_database`` sources only),
    but carried no explicit guard against a future addition that did."""

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
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="Source DB",
        config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                     "database": "AED_SORENTO", "username": "readonly"},
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


def test_pull_mode_never_reaches_the_paged_dispatch_or_either_inline_gate(db, monkeypatch):
    import modules.autocount.sync as sync_module
    from app.jobs.service import JobService
    from modules.autocount.services.sync_service import SyncService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    factory_calls = []

    def spy_factory(impl):
        factory_calls.append(impl)
        return lambda *a, **kw: pytest.fail(
            "the constructed source's own factory call must never be invoked "
            "for a pull-mode task"
        )

    paged_calls = []
    push_calls = []

    monkeypatch.setattr(sync_module, "source_factory", spy_factory)
    monkeypatch.setattr(
        sync_module, "_run_paged_sql_db",
        lambda *a, **kw: paged_calls.append((a, kw)),
    )
    monkeypatch.setattr(
        SyncService, "auto_push",
        lambda self, *a, **kw: push_calls.append((a, kw)) or {"pushed": 0},
    )

    conn = _connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_SQL_DB, etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
        source_config={
            "connectionId": conn.id,
            "query": "SELECT item_code, description, last_modified FROM item",
            "keyColumns": ["item_code"],
            "watermarkColumn": "last_modified",
            "comparedColumns": [],
        },
    )
    db.add(config)
    db.commit()

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    assert factory_calls == [], "source_factory must never be called for a pull-mode task"
    assert paged_calls == [], "_run_paged_sql_db must never be called for a pull-mode task"
    assert push_calls == [], "auto_push must never be called for a pull-mode task"
    assert db.query(AcStagedRecord).filter(AcStagedRecord.company_id == company.id).count() == 0
