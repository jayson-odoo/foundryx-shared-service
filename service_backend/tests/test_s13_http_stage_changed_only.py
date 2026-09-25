"""Plan 13 S0 - Group B, AC-13-11: changed-only staging for EVERY
`autocount_http` task (closes BL-SS-238). RED before the coder.

Uses ``ENTITY_PRODUCT`` (flat HTTP task, no combine, no Decimal fields) -
D6 is explicitly "every `autocount_http` task", never a stock special case,
so pinning it against the entity this repo's OWN HTTP lifecycle tests
(`test_autocount_http_lifecycle.py`) already use avoids the unrelated
Decimal/`raw_json` defect `test_s13_stock_reconcile_delete.py` documents for
the combine path, and proves the mechanism generically as the AC demands.

``FetchResult`` carries no ``changed_refs`` field at all today (grepped
2026-09-25 - `modules/autocount/sources.py`'s dataclass stops at
`combine_metadata`) and ``_stage_documents`` accepts no ``changed_refs``/
``ref_fn`` kwargs (`sync.py`) - every test below is expected to fail either
on a plain ``AttributeError``/``TypeError`` naming the missing surface, or
(for the full-run cases) because TODAY every mapped record is staged on
every run regardless of whether it changed (the literal bug AC-13-11
closes) - never a broken-test crash.

Pins: AC-13-11 (a)-(f).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import httpx
import pytest

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source.client import HttpApiClient
from modules.autocount.models import AcCompany, AcStagedRecord
from modules.autocount.repositories import EntityConfigRepository
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _open_connection(db) -> Connection:
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


def _http_raw(connection_id, **overrides) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": connection_id,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": None,  # no-watermark: every run is a full diff
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(conn.id))
    yield db, company
    db.close()


def _staged_rows(db, company_id: str):
    return (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.entity_type == ENTITY_PRODUCT,
        )
        .all()
    )


def _run(db, company_id: str, handler) -> None:
    import modules.autocount.http_source.source as http_source_module

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    orig = http_source_module.HttpApiClient
    http_source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(  # type: ignore
        base_url, transport=stub_transport
    )
    try:
        job = JobService(db).create(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": company_id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
        )
        run_autocount_sync(db, job)
    finally:
        http_source_module.HttpApiClient = orig


def _item(code: str, *, last_modified="2026-08-01T09:00:00", is_active="T") -> Dict[str, Any]:
    return {"ItemCode": code, "Description": code, "LastModified": last_modified, "IsActive": is_active}


def _bare_array(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    return handler


# ── surface existence (collection-safe pins) ────────────────────────────────


def test_fetch_result_has_no_changed_refs_field_yet():
    from modules.autocount.sources import FetchResult

    result = FetchResult()
    assert not hasattr(result, "changed_refs")


def test_stage_documents_rejects_changed_refs_kwarg_today():
    import inspect

    from modules.autocount.sync import _stage_documents

    params = inspect.signature(_stage_documents).parameters
    assert "changed_refs" not in params
    # ``ref_fn`` already exists (plan sprint-5/03 S2, AC-03-11/12) - only
    # ``changed_refs`` is new for this plan.
    assert "ref_fn" in params


# ── (a) unchanged, already-delivered pair is never re-staged ───────────────


def test_a_an_unchanged_already_delivered_pair_is_not_restaged(rig):
    db, company = rig
    _run(db, company.id, _bare_array([_item("A1")]))
    first = _staged_rows(db, company.id)
    assert len(first) == 1
    from modules.autocount.models import STAGED_PUSHED

    first[0].status = STAGED_PUSHED
    db.commit()

    _run(db, company.id, _bare_array([_item("A1")]))
    second = _staged_rows(db, company.id)
    assert len(second) == 1, (
        "AC-13-11(a): an unchanged, already-delivered pair must not stage a "
        "second row - today's stage-everything behaviour (BL-SS-238) does"
    )


# ── (b) a qty/field-only change stages exactly one record ──────────────────


def test_b_a_field_only_change_stages_exactly_one_record(rig):
    db, company = rig
    _run(db, company.id, _bare_array([_item("A1"), _item("A2")]))
    from modules.autocount.models import STAGED_PUSHED

    for row in _staged_rows(db, company.id):
        row.status = STAGED_PUSHED
    db.commit()

    _run(
        db, company.id,
        _bare_array([_item("A1"), _item("A2", last_modified="2026-09-01T09:00:00")]),
    )
    newly_staged = [
        r for r in _staged_rows(db, company.id) if r.status != STAGED_PUSHED
    ]
    assert len(newly_staged) == 1, newly_staged
    assert newly_staged[0].source_ref.endswith(":A2")


# ── (c) Re-push (hashes cleared) re-stages everything ───────────────────────


def test_c_repush_clears_hashes_and_restages_every_record(rig):
    db, company = rig
    # `repush_task` refuses a draft task - stamp the preview gate and
    # activate first (mirrors `test_autocount_http_lifecycle.py`'s
    # `_stamp_previewed` + `activate_task` pattern).
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    config.last_preview_at = NOW
    config.result_columns = ["ItemCode", "Description", "LastModified", "IsActive"]
    db.commit()
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    _run(db, company.id, _bare_array([_item("A1"), _item("A2")]))
    from modules.autocount.models import STAGED_PUSHED

    for row in _staged_rows(db, company.id):
        row.status = STAGED_PUSHED
    db.commit()

    EtlService(db).repush_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    _run(db, company.id, _bare_array([_item("A1"), _item("A2")]))
    newly_staged = [
        r for r in _staged_rows(db, company.id) if r.status != STAGED_PUSHED
    ]
    assert len(newly_staged) == 2, (
        "AC-13-11(c): after Re-push every ref reads as changed and must "
        "restage, even with an unchanged canonical value"
    )


# ── (f) control: a sql_db task's staging is untouched ───────────────────────


def test_f_control_a_sql_db_task_stages_every_record_every_run(session_factory):
    """AC-13-11(f) - the SQL source reports no changed set at all
    (`FetchResult.changed_refs` stays ``None`` for every non-HTTP source),
    so `_stage_documents` must keep staging every mapped record on every
    run for it, byte-identical to before. This one is a CONTROL: it should
    already pass today (nothing here is new for the SQL path) and must
    KEEP passing once AC-13-11 ships - proving the changed-only rule never
    leaks onto a source that cannot support it."""
    import sqlalchemy as sa
    from sqlalchemy.pool import StaticPool

    from app.secrets import encrypt_secret
    from modules.autocount.canonical.masters import ENTITY_CUSTOMER
    from modules.autocount.models import AcFieldMapping
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sql_source.runtime import RUNTIME

    db = session_factory()
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn_:
        conn_.exec_driver_sql("CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT)")
        conn_.exec_driver_sql("INSERT INTO debtor VALUES ('300-A001', 'Acme')")

    sql_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="db",
        config_json={"dbType": "postgresql", "host": "x", "port": "5432", "database": "d", "username": "u"},
        credentials_json=encrypt_secret({"password": "p"}), is_active=True,
    )
    db.add(sql_conn)
    db.flush()
    RUNTIME.put_engine(sql_conn.id, engine)
    # The COMPANY's own primary connection stays an `autocount` (API)
    # provider - `seed_company_defaults` seeds nothing at all for a company
    # whose primary connection is already `sql_database` (D13, "a DATABASE
    # company is born EMPTY"). The SQL connection above is wired onto THIS
    # ONE entity's `source_config.connectionId` below instead, exactly how
    # `test_autocount_reconcile_push.py`'s own rig mixes the two.
    api_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
    )
    db.add(api_conn)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api_conn.id, database_name="AED_X",
        company_name="X", name="X", is_active=True, sorento_company_code="X",
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    for row in (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_CUSTOMER,
        )
        .all()
    ):
        flat = {"code": "acc_no", "name": "company_name"}
        if row.canonical_field in flat:
            row.source_path = flat[row.canonical_field]
        else:
            row.is_enabled = False
    db.commit()

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER)
    config.source_impl = "sql_db"
    config.source_config = {
        "connectionId": sql_conn.id, "query": "SELECT acc_no, company_name FROM debtor",
        "keyColumns": ["acc_no"], "watermarkColumn": None, "comparedColumns": [],
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    config.result_columns = ["acc_no", "company_name"]
    db.commit()

    def _sql_run():
        job = JobService(db).create(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": company.id, "entityType": ENTITY_CUSTOMER, "mode": "manual"},
        )
        run_autocount_sync(db, job)

    _sql_run()
    from modules.autocount.models import STAGED_PUSHED

    rows1 = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company.id,
            AcStagedRecord.entity_type == ENTITY_CUSTOMER,
        )
        .all()
    )
    assert len(rows1) == 1
    rows1[0].status = STAGED_PUSHED
    db.commit()

    _sql_run()
    rows2 = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company.id,
            AcStagedRecord.entity_type == ENTITY_CUSTOMER,
        )
        .all()
    )
    assert len(rows2) == 2, (
        "control: an unchanged SQL row stages AGAIN every run today (no "
        "hash comparison at all for the SQL path pre-reconcile) - this "
        "must stay true, never accidentally narrowed by AC-13-11's HTTP-"
        "only change"
    )
    db.close()
    RUNTIME.dispose_all()
