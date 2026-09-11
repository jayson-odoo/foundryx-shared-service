"""Sprint-5/08 S3 - HTTP task lifecycle: source-change demotion, the sweep,
and the no-SQL-engine / round-trip / repush guarantees (AC-08-28..30).

RED before the coder, for three DIFFERENT reasons pinned per test:

* ``scheduler.sweep_etl_tasks`` selects ONLY ``AcEntityConfig.source_impl ==
  SOURCE_IMPL_SQL_DB`` (``modules/autocount/scheduler.py:100``, read
  2026-09-12) - an ``autocount_http`` task is never selected, so
  ``test_sweep_enqueues_due_sql_and_due_http`` fails on the fired count.
* ``EtlService.repush_task`` HARD-refuses any ``source_impl`` other than
  ``sql_db`` (``services/etl_service.py:1771``, ``EtlStateError("Re-push
  applies to database tasks only.")``) - the exact opposite of AC-08-30's
  "works unchanged for HTTP tasks"; ``test_repush_task_works_for_http_task``
  fails with that exact exception today.
* Everything routed through ``EtlService.update_task`` fails for the same
  reason as ``test_autocount_http_task_config.py`` - the method is 100%
  SQL-shaped today (no ``sourceImpl`` branch at all).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    AcCompany,
    AcEntityConfig,
    AcRowHash,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sync import AUTOCOUNT_SYNC

try:
    from modules.autocount.models import SOURCE_IMPL_AUTOCOUNT_HTTP
except ImportError:  # pragma: no cover - expected until the coder adds it
    SOURCE_IMPL_AUTOCOUNT_HTTP = "autocount_http"

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_raw(**overrides) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


def _transport(rows=None):
    body = rows if rows is not None else [{"ItemCode": "A1"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── AC-08-28: demotion to draft on source-impl/connection/path change ────────


def test_changing_connection_on_active_http_task_returns_draft_and_keeps_hashes(db):
    conn_a = _open_connection(db)
    company = _company(db, conn_a.id)
    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn_a.id)
    )
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    from modules.autocount.repositories import RowHashRepository

    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {"MOCHA:A1": "x" * 64}, seen_at=None
    )

    conn_b = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST 2",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        is_active=True,
    )
    db.add(conn_b)
    db.commit()

    updated = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn_b.id)
    )
    assert updated.etl_status == ETL_STATUS_DRAFT
    assert db.query(AcRowHash).filter(AcRowHash.company_id == company.id).count() == 1


# ── AC-08-29: the sweep enqueues due HTTP tasks too ──────────────────────────


def test_sweep_enqueues_due_sql_and_due_http(db):
    from modules.autocount.models import SOURCE_IMPL_SQL_DB
    from modules.autocount.canonical.masters import ENTITY_CUSTOMER

    sql_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="SQL",
        config_json={"dbType": "postgresql", "database": "AED"}, is_active=True,
    )
    db.add(sql_conn)
    db.commit()
    sql_company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=sql_conn.id, database_name="AED",
        company_name="AED", name="AED", is_active=True,
    )
    db.add(sql_company)
    db.commit()
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=sql_company.id, entity_type=ENTITY_CUSTOMER,
            source_impl=SOURCE_IMPL_SQL_DB, etl_status=ETL_STATUS_ACTIVE,
            source_config={
                "connectionId": sql_conn.id, "query": "SELECT 1 AS acc_no",
                "keyColumns": ["acc_no"], "watermarkColumn": None, "comparedColumns": [],
                "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            },
            next_incremental_at=NOW - timedelta(minutes=1),
        )
    )

    open_conn = _open_connection(db)
    http_company = _company(db, open_conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=http_company.id, entity_type=ENTITY_PRODUCT,
            source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_ACTIVE,
            source_config=_http_raw(connectionId=open_conn.id),
            next_incremental_at=NOW - timedelta(minutes=1),
        )
    )
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result["fired"] == 2, result


def test_sweep_overlap_guard_skips_http_task_in_flight(db):
    from app.models.background_job import JOB_RUNNING

    open_conn = _open_connection(db)
    company = _company(db, open_conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_ACTIVE,
        source_config=_http_raw(connectionId=open_conn.id),
        next_incremental_at=NOW - timedelta(minutes=1),
    )
    db.add(config)
    db.commit()
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
            payload_json={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "incremental"},
            heartbeat_at=NOW,
        )
    )
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result["skipped"] == 1, result
    assert result["fired"] == 0, result


# ── AC-08-30: no SQL engine, round-trip, repush ──────────────────────────────


def test_update_task_http_never_builds_sql_engine(db, monkeypatch):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    calls = []
    monkeypatch.setattr(
        EtlService, "_engine", lambda self, c: calls.append(c) or (_ for _ in ()).throw(AssertionError("SQL engine built for an HTTP task"))
    )
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id))
    assert calls == []


def test_etl_task_view_round_trips_http_source_config(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )
    assert view.source_config.get("path") == "/itembypage"
    assert view.source_config.get("keyFields") == ["ItemCode"]

    fetched = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert fetched.source_config.get("path") == "/itembypage"


def test_repush_task_works_for_http_task(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id))
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    result = EtlService(db).repush_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert result.status == ETL_STATUS_ACTIVE
