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
        # `activate_task` refuses ANY company (any source_impl) with no
        # Sorento company code - a pre-existing, universal gate
        # (`test_activate_is_refused_without_a_sorento_company_code`,
        # test_autocount_etl_task_routes.py:706) this fixture must satisfy
        # to reach the demotion/repush behaviour these tests actually cover.
        sorento_company_code="MOCHA",
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


def _stamp_previewed(
    db, company_id: str, entity_type: str = ENTITY_PRODUCT, *, stamp_result_columns: bool = True
) -> None:
    """B3 (sprint-5/08 review round 1) widened ``activate_task``'s
    "run a preview first" gate to HTTP tasks too (it used to bypass them
    entirely) - these lifecycle tests are about DEMOTION/repush, not the
    preview gate itself, so they stamp it directly rather than running a
    real dry-run against a consumer. ``stamp_result_columns`` defaults True
    (a REAL preview always stamps `result_columns` alongside
    `last_preview_at`, `services/etl_service.py:834`) - pass False to
    reproduce the round-2 B-A bug scenario (an API-direct save/activate that
    never ran a preview at all leaves `result_columns` None)."""
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company_id, entity_type)
    config.last_preview_at = NOW
    if stamp_result_columns:
        config.result_columns = ["ItemCode", "Description", "LastModified", "IsActive"]
    db.commit()


# ── AC-08-28: demotion to draft on source-impl/connection/path change ────────


def test_changing_connection_on_active_http_task_returns_draft_and_keeps_hashes(db):
    conn_a = _open_connection(db)
    company = _company(db, conn_a.id)
    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn_a.id)
    )
    _stamp_previewed(db, company.id)
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


def test_sweep_enqueues_due_sql_and_due_http(db, monkeypatch):
    """AC-08-29 - the sweep's SELECTION logic fires both a due SQL and a due
    HTTP task; it never has to actually RUN either job to prove that (B4,
    sprint-5/08 review round 1: this test used to run under the suite's
    always-eager job setting, which executed the enqueued job INLINE and
    made a real network call to ``hapi.sorento.cc.cd`` on every pytest run).
    Job dispatch itself (`run_job_task.delay`/`apply_async`) is the SAME
    seam ``tests/test_background_jobs.py`` already stubs - reused here
    rather than invented fresh."""
    from app.config import settings
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    dispatched: list = []
    monkeypatch.setattr(
        worker_module.run_job_task, "delay", lambda job_id: dispatched.append(job_id)
    )
    monkeypatch.setattr(
        worker_module.run_job_task,
        "apply_async",
        lambda args=None, queue=None, **kw: dispatched.append((args, queue)),
    )
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
    assert len(dispatched) == 2, dispatched


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
    _stamp_previewed(db, company.id)
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    result = EtlService(db).repush_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert result.status == ETL_STATUS_ACTIVE


# ── B3 (sprint-5/08 review round 1) - the activate-once gate is now uniform,
# and Review & Activate's consumer dry-run genuinely dispatches on
# source_impl instead of hardcoding SqlDbSource for an HTTP task. ──────────


def test_activate_http_task_without_a_preview_409(db):
    from modules.autocount.services.etl_service import EtlStateError

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    with pytest.raises(EtlStateError) as exc:
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert "preview" in str(exc.value).lower()


def test_activate_http_task_refused_409_when_never_previewed_result_columns_none(db):
    """B-A (sprint-5/08 review round 2 blocker), route (b): an API-direct PUT
    with no preview ever run leaves `result_columns` None and
    `comparedFields` resolves to `[]` - `_stamp_previewed` here fakes ONLY
    `last_preview_at` (the way an operator hand-editing the row, or a client
    calling the API directly and never hitting `/autocount/http/preview`,
    would leave the task), so the activate-once gate must refuse rather than
    let a task with no working change detection go active.

    Round 3 SHOULD-FIX 1: this is an `EtlStateError` (409), same shape as
    the two sibling activate gates above - an `EtlValidationError` here was
    dropped by `_raise_task`'s `EtlStateError` branch (this task never went
    through `_field_errors`), leaving the operator with a generic "fix the
    highlighted fields" and nothing highlighted."""
    from modules.autocount.services.etl_service import EtlStateError

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    # last_preview_at only - result_columns stays None (never previewed).
    _stamp_previewed(db, company.id, stamp_result_columns=False)
    with pytest.raises(EtlStateError) as exc:
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert "Test the endpoint again" in str(exc.value)


def test_extract_and_map_dispatches_http_api_source_never_sql_engine(db, monkeypatch):
    """B3 - ``preview_task``'s dry-run (``_extract_and_map``) used to
    unconditionally build a ``SqlDbSource``, so an HTTP task's Review &
    Activate preview either crashed or silently mapped nothing. Proven
    directly against ``_extract_and_map`` (the private dispatch point)
    rather than through a full Sorento consumer round trip, which
    ``sink_for_company`` does not (yet) accept a stub transport for.

    ``_extract_and_map`` has no ``transport`` parameter of its own (it is
    an internal dispatch point, never a public seam) - the network is
    stubbed the same way ``client_from_connection`` gets stubbed elsewhere
    in this module: at the class the source builds
    (``http_source.source.HttpApiClient``), never a REAL call to
    ``hapi.sorento.cc.cd``."""
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    calls: list = []
    monkeypatch.setattr(
        EtlService, "_engine",
        lambda self, c: calls.append(c) or (_ for _ in ()).throw(
            AssertionError("SQL engine built for an HTTP task's preview")
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"ItemCode": "A1", "Description": "Item A1"}])

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    service = EtlService(db)
    records, current_refs, page_complete = service._extract_and_map(
        DEFAULT_TENANT_ID, company, config, ENTITY_PRODUCT
    )
    assert calls == [], "the SQL engine must never be built for an HTTP task's preview"
    assert page_complete is None
    assert current_refs == ["MOCHA:A1"]
    assert len(records) == 1


# ── B-B (sprint-5/08 review round 2 blocker) - preview_task never catches
# HttpSourceError, so Review & Activate's Preview on an HTTP task escaped as
# a bare 500 for every source failure (a 404 path, timeout, shape change) -
# AC-08-23 requires the failure to name page + status. ──────────────────────


class _PreviewableDummySink:
    """`hasattr(sink, "dry_run")` is all `preview_task` checks to flip
    `previewable` True - the source must fail BEFORE `dry_run` is ever
    reached, so this stub asserts it never is."""

    name = "sorento"

    def dry_run(self, records):  # pragma: no cover - must never be reached
        raise AssertionError("the source must fail before the sink is asked anything")


def test_preview_task_maps_http_source_failure_to_422_naming_page_and_status(db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.services.etl_service import EtlAnchorError

    monkeypatch.setattr(
        CompanyService, "sink_for_company",
        lambda self, tenant_id, company, entity_type: _PreviewableDummySink(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )
    from modules.autocount.http_source.errors import HttpSourceError

    with pytest.raises(HttpSourceError) as exc:
        EtlService(db).preview_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert exc.value.page == 1
    assert exc.value.status == 500
    assert "page 1" in exc.value.message


def test_preview_route_maps_http_source_failure_to_422_never_a_bare_500(client, db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        CompanyService, "sink_for_company",
        lambda self, tenant_id, company, entity_type: _PreviewableDummySink(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "page 1" in body["message"]
    assert "500" in body["message"]


# ── SF-2 (sprint-5/08 review round 2) - a real RUN's HTTP source failures must
# land as a WARNING with `error_code` set (mirrors the SQL delete guard's own
# DELETE_GUARD branch), never the generic `except Exception` crash branch
# (stack trace, `last_run_error_code = None`) - AC-08-38 needs the Runs tab to
# show the error code AND page number. ─────────────────────────────────────


def test_run_autocount_sync_http_status_failure_sets_error_code_and_names_page(
    db, monkeypatch, caplog
):
    import logging

    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(
            200,
            json={
                "TotalCount": 3, "Page": page, "PageSize": 1, "TotalPages": 3,
                "Data": [{"ItemCode": f"A{page}", "LastModified": "2026-08-01T09:00:00", "IsActive": "T"}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        run_autocount_sync(db, job)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.last_run_error_code == "HTTP_STATUS"
    assert "page 3" in (config.last_run_error or "")
    assert not any(r.exc_info for r in caplog.records), (
        "an HTTP source failure must log a WARNING, never a stack trace"
    )


def test_run_autocount_sync_http_delete_guard_maps_to_delete_guard_code(db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.repositories import EntityConfigRepository, RowHashRepository
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []})

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module,
        "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=conn.id, path="/itembypage", keyFields=["ItemCode"]),
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {"MOCHA:GONE": "x" * 64}, seen_at=None,
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "reconcile"},
    )
    run_autocount_sync(db, job)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.last_run_error_code == "DELETE_GUARD"
