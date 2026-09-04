"""AutoCount document mapping -> Sorento import parity (sprint-5/02, S2+S3).

RED tests written BEFORE the coder, from three inputs:

* the UAC (`documentation/plans/sprint-5/02-autocount-document-mapping-
  acceptance-criteria.md`, Groups A-E + AC-02-27);
* the plan (`02-autocount-document-mapping.md` sections 2.1-2.5, 3, 4) +
  the Sorento addendum (as-built semantics, sections 3/5/9/12);
* the Phase 1 frontend contract - `service_frontend/services/autocount-
  service.mock.ts` (`withPhase1DocumentMappingMock`), `types/autocount.ts`,
  and `autocount-document-mapping.mock.test.ts` (already green - this is
  the wire shape the backend must match).

Every test below seeds its OWN tenant/connection/company/task chain (no
shared fixtures across tests) - mirrors `tests/test_autocount_documents.py`
and `tests/test_autocount_sql_db_source.py` fixture shape. `DEFAULT_TENANT_ID`
is reused across tests (each test's DB is a fresh in-memory SQLite via the
function-scoped `session_factory` fixture, so this is not row-sharing).

Where the target symbol/behaviour does not exist yet, the test imports it
LOCALLY (inside the test function) so a missing name fails only that one
test (ImportError/AttributeError/TypeError), never the whole module's
collection - this is the sanctioned red-test shape for AC-02-04 ("the
`document_line_rows` convention symbol no longer exists") and is used
consistently below for the same reason: a symbol that plainly does not
exist today is exactly the right red reason for a slice that has not been
built yet.

ASSUMPTIONS this file makes about not-yet-chosen names (flagged so the
coder/reviewer can reconcile, per the plan's naming intent):
* `modules.autocount.backfill.backfill_document_line_mapping_pickers(db,
  tenant_id, company_id, entity_type) -> int` - the AC-02-05 migration
  backfill function, mirroring the existing `backfill_*_defaults(bind, ...)`
  family's "testable ordinary function" shape but at the ORM/session level
  (it must build real `AcFieldMapping` rows, not raw DDL).
* `modules.autocount.canonical.documents.ENTITY_SHIPPING_ORDER` /
  `CanonicalShippingOrder` / `CanonicalShippingOrderLine` - named exactly per
  plan section 2.3 / addendum section 3.
"""
from __future__ import annotations

import types
from decimal import Decimal
from typing import Dict, List

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret

from modules.autocount.canonical.documents import (
    DOCUMENT_STATUS_VALUES,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    CanonicalPurchaseOrder,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
)
from modules.autocount.mapping import (
    ENTITY_PROFILES,
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    build_mapping_rows_for_run,
    flat_profile,
)
from modules.autocount.models import (
    ETL_STATUS_DRAFT,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
    STAGED,
    STAGED_OP_DELETE,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import (
    AutocountServiceError,
    CompanyService,
    MappingWriteRow,
)
from modules.autocount.services.etl_service import (
    ETL_ENTITY_TYPES,
    EtlService,
    validate_source_config,
)
from modules.autocount.sinks_sorento import SorentoSink, sorento_supports_entity
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.sql_source.errors import SqlDeleteGuardExceeded
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import SqlDbSource

PASSWORD = "S3cret!Pa55"


# ── shared fixture helpers (each test builds its OWN chain) ─────────────────


def _sql_connection(db, engine: sa.engine.Engine, *, database: str, name: str) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider="sql_database",
        type="erp",
        name=name,
        config_json={
            "dbType": "postgresql",
            "host": "db.example.com",
            "port": "5432",
            "database": database,
            "username": "readonly",
        },
        credentials_json=encrypt_secret({"password": PASSWORD}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    RUNTIME.put_engine(conn.id, engine)
    return conn


def _company(db, connection_id: str, *, database: str, name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID,
        connection_id=connection_id,
        database_name=database,
        company_name=name,
        name=name,
        is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


HEADER_QUERY = (
    "SELECT doc_key, doc_no, status, cancelled, doc_date, last_modified "
    "FROM so_header"
)
LINE_QUERY = (
    "SELECT dtl_key, item_code, qty_ordered, qty_delivered, seq FROM so_line "
    "WHERE doc_key = :doc_key"
)


def _source_engine(
    header_rows: List[tuple], lines_by_doc: Dict[str, List[tuple]]
) -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, cancelled TEXT, doc_date TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT, qty_delivered TEXT, seq INTEGER)"
        )
        for row in header_rows:
            conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?, ?)", row)
        for doc_key, lines in lines_by_doc.items():
            for dtl_key, item_code, qty, delivered, seq in lines:
                conn.exec_driver_sql(
                    "INSERT INTO so_line VALUES (?, ?, ?, ?, ?, ?)",
                    (dtl_key, doc_key, item_code, qty, delivered, seq),
                )
    return engine


def _source_engine_typed(
    header_rows: List[tuple], lines_by_doc: Dict[str, List[tuple]]
) -> sa.engine.Engine:
    """Like `_source_engine`, but `doc_date`/`last_modified` are declared
    DATE/TIMESTAMP with `detect_types=PARSE_DECLTYPES` so a live column-type
    preview (`EtlService.update_task`'s real `run_preview` sniff) reads them
    back as Python `date`/`datetime` objects (orderable), not `str`. Needed
    only by tests that go through `update_task` for real - `SqlDbSource`-
    level tests never sniff types this way (they read `result_columns` off
    the stored config), so `_source_engine`'s plain TEXT columns are fine
    there. `header_rows`' 5th/6th elements are `date`/`datetime` objects.
    """
    import sqlite3

    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False, "detect_types": sqlite3.PARSE_DECLTYPES},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, cancelled TEXT, doc_date DATE, last_modified TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT, qty_delivered TEXT, seq INTEGER)"
        )
        for row in header_rows:
            conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?, ?)", row)
        for doc_key, lines in lines_by_doc.items():
            for dtl_key, item_code, qty, delivered, seq in lines:
                conn.exec_driver_sql(
                    "INSERT INTO so_line VALUES (?, ?, ?, ?, ?, ?)",
                    (dtl_key, doc_key, item_code, qty, delivered, seq),
                )
    return engine


def _document_config(
    db, company: AcCompany, connection_id: str, entity_type: str = ENTITY_SALES_ORDER, **overrides
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID,
        company_id=company.id,
        entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
        etl_status=ETL_STATUS_DRAFT,
    )
    source_config = {
        "connectionId": connection_id,
        "query": HEADER_QUERY,
        "lineQuery": LINE_QUERY,
        "keyColumns": ["doc_key"],
        "watermarkColumn": "last_modified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "doc_date",
        "lineKeyColumn": "dtl_key",
        "lineProductColumn": "item_code",
        "lineWarehouseColumn": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    source_config.update(overrides)
    config.source_config = source_config
    config.result_columns = ["doc_key", "doc_no", "status", "cancelled", "doc_date", "last_modified"]
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company: AcCompany, config: AcEntityConfig) -> SourceContext:
    return SourceContext(
        db=db,
        tenant_id=DEFAULT_TENANT_ID,
        company=company,
        entity_config=config,
        company_service=CompanyService(db),
    )


def _seed_line_row(db, company: AcCompany, entity_type: str, source_path: str, canonical_field: str,
                    transform: str, *, required: bool = False) -> AcFieldMapping:
    row = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID,
        company_id=company.id,
        entity_type=entity_type,
        scope=SCOPE_LINE,
        source_path=source_path,
        canonical_field=canonical_field,
        transform=transform,
        is_required=required,
        is_enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ═══════════════════════════════════════════════════════════════════════════
# Group A - Line mapping is operator-editable
# ═══════════════════════════════════════════════════════════════════════════


def test_line_rows_persist_with_scope(session_factory):
    """AC-02-01: header `currency` and line `currency` are distinct rows by
    scope, and a header re-map never deletes a line row.

    Today's gap: `CompanyService.replace_mapping` hardcodes `scope=SCOPE_HEADER`
    on every write and calls `mappings.delete_unknown(..., accepted |
    PRESERVED_CANONICAL_FIELDS)` with NO scope awareness - a line row whose
    canonical_field (`product_ref`) is not itself a HEADER-accepted field (it
    never is) is swept as "stale" the instant the operator re-saves the header
    mapping. This is a real, present bug this test pins.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_LINE1", name="src")
    company = _company(db, conn.id, database="AED_LINE1", name="Line Co")
    _document_config(db, company, conn.id)

    # A pre-existing LINE row (as if seeded by a preset or a prior save).
    _seed_line_row(
        db, company, ENTITY_SALES_ORDER, "ItemAutoKey", "product_ref", "ref_product",
        required=True,
    )
    _seed_line_row(
        db, company, ENTITY_SALES_ORDER, "DtlKey", "source_ref", "string", required=True,
    )

    service = CompanyService(db)
    # Re-map ONLY the header - a header re-map must never touch line rows.
    # Both required header fields (`so_number` + `status`) are supplied so the
    # save succeeds on its own terms; the assertion under test is about the
    # LINE rows surviving, not about header completeness.
    service.replace_mapping(
        DEFAULT_TENANT_ID,
        company.id,
        ENTITY_SALES_ORDER,
        [
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
            MappingWriteRow(source_path="Status", transform="string", sorento_field="status"),
        ],
    )

    remaining = db.query(AcFieldMapping).filter(
        AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
        AcFieldMapping.company_id == company.id,
        AcFieldMapping.entity_type == ENTITY_SALES_ORDER,
        AcFieldMapping.scope == SCOPE_LINE,
    ).all()
    assert {r.canonical_field for r in remaining} == {"product_ref", "source_ref"}, (
        "a header-only save must never delete existing LINE rows - "
        f"got {[r.canonical_field for r in remaining]}"
    )

    # `MappingWriteRow` must itself accept `scope='line'` so a save CAN target
    # the line scope (AC-02-01's write path) - this currently raises
    # TypeError (no such field), which is the second half of this gap.
    MappingWriteRow(
        source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"
    )
    db.close()


def test_mapping_get_line_catalog(session_factory):
    """AC-02-02: GET mapping for a document entity carries `lineSorentoFields`
    (source_ref/product_ref required, qty fields, fallback fields) and
    `lineAcFields` == the task's persisted `line_result_columns`; header
    `sorentoFields` gains the fallback fields (customer_code/name/agent_code
    for SO; supplier_code/name/agent_code for PO/SPO).

    Today's gap: `CompanyService.MappingView`/`_mapping_view` carry only
    `sorento_fields`/`ac_fields` - no line catalog at all.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_LINE2", name="src")
    company = _company(db, conn.id, database="AED_LINE2", name="Line Co 2")
    _document_config(db, company, conn.id)

    view = CompanyService(db).mapping_view(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)

    line_fields = getattr(view, "line_sorento_fields", None)
    assert line_fields is not None, "MappingView has no `line_sorento_fields` yet (AC-02-02)"
    names = {f.field for f in line_fields}
    assert {"source_ref", "product_ref", "qty_ordered"} <= names
    required = {f.field for f in line_fields if f.required}
    assert {"source_ref", "product_ref", "qty_ordered"} <= required

    line_ac_fields = getattr(view, "line_ac_fields", None)
    assert line_ac_fields is not None, "MappingView has no `line_ac_fields` yet (AC-02-02)"

    header_names = {f.field for f in view.sorento_fields}
    assert {"customer_code", "customer_name", "agent_code"} <= header_names, (
        "header sorentoFields must gain the fallback fields (AC-02-14)"
    )
    db.close()


def test_line_ref_pairing_422(session_factory):
    """AC-02-03: `product_ref`<->`ref_product`, `warehouse_ref`<->`ref_warehouse`
    are a locked pair; `source_ref`/`product_ref`/`qty_ordered` required the
    moment any line row is saved; only `lineSorentoFields` targets accepted.

    Today's gap: `MappingWriteRow` has no `scope` field at all, so a line-row
    save cannot even be attempted through the service yet - every case below
    fails at construction with a clean TypeError (the AC-02-01 prerequisite).
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_LINE3", name="src")
    company = _company(db, conn.id, database="AED_LINE3", name="Line Co 3")
    _document_config(db, company, conn.id)
    service = CompanyService(db)

    def _save(rows):
        service.replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, rows)

    # (a) product_ref without ref_product -> 422.
    with pytest.raises(AutocountServiceError):
        _save([
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
            MappingWriteRow(source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"),
            MappingWriteRow(source_path="ItemAutoKey", transform="string", sorento_field="product_ref", scope="line"),
            MappingWriteRow(source_path="Qty", transform="decimal", sorento_field="qty_ordered", scope="line"),
        ])

    # (b) missing product_ref/qty_ordered when a line row is saved -> 422.
    with pytest.raises(AutocountServiceError):
        _save([
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
            MappingWriteRow(source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"),
        ])

    # (c) an unaccepted line target -> 422.
    with pytest.raises(AutocountServiceError):
        _save([
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
            MappingWriteRow(source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"),
            MappingWriteRow(source_path="ItemAutoKey", transform="ref_product", sorento_field="product_ref", scope="line"),
            MappingWriteRow(source_path="Qty", transform="decimal", sorento_field="qty_ordered", scope="line"),
            MappingWriteRow(source_path="Bogus", transform="string", sorento_field="not_a_real_field", scope="line"),
        ])
    db.close()


def test_run_uses_persisted_line_rows(session_factory):
    """AC-02-04: `build_mapping_rows_for_run` = header rows + PERSISTED line
    rows; the fixed `document_line_rows` convention is GONE. A line's
    `source_ref` still composes `{header_source_ref}:{DtlKey}`.
    """
    # The fixed-convention generator must no longer exist.
    with pytest.raises((ImportError, AttributeError)):
        import modules.autocount.mapping as mapping_module

        if not hasattr(mapping_module, "document_line_rows"):
            raise AttributeError("document_line_rows removed, as required")
        # It still exists today - force the assertion to register as a
        # failure (not a false pass) by asserting the desired absence.
        assert not hasattr(mapping_module, "document_line_rows"), (
            "mapping.document_line_rows must be REMOVED once line rows are "
            "operator-persisted (AC-02-04) - it still exists."
        )

    # Supporting behaviour: PERSISTED line rows (not the fixed generator)
    # drive the run and compose the two-tier ref scheme end to end.
    db = session_factory()
    header_rows = [
        MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
        MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
        MappingRow("Status", "status", "string", SCOPE_HEADER),
        MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
        MappingRow("ItemAutoKey", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
        MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
    ]
    rows = build_mapping_rows_for_run(
        ENTITY_SALES_ORDER, header_rows, is_sql_db_source=True, source_config={},
    )
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_X",
    )
    mapped = engine.map_document({
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open",
        "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"}],
    })
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.lines[0].source_ref == "AED_X:D1:L1"
    db.close()


def test_push_carries_full_line_set(session_factory):
    """AC-02-04b: a header whose ONE line changed still pushes its FULL line
    set (the line query runs per :doc_key, never a delta) - using rows saved
    through the OPERATOR-EDITABLE persistence path (`CompanyService.
    replace_mapping`, AC-02-01), not a hand-built `MappingRow` list. This is
    what distinguishes AC-02-04b from AC-02-04's engine-composition pin:
    here the line rows must have actually been SAVED (scope='line') and then
    re-read via `mapping_rows()` before the push-time full-set property is
    checked.
    """
    db = session_factory()
    engine_sql = _source_engine([], {})
    conn = _sql_connection(db, engine_sql, database="AED_PUSH1", name="src")
    company = _company(db, conn.id, database="AED_PUSH1", name="Push Co")
    _document_config(db, company, conn.id)

    service = CompanyService(db)
    service.replace_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        [
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
            MappingWriteRow(source_path="Status", transform="string", sorento_field="status"),
            MappingWriteRow(source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"),
            MappingWriteRow(source_path="ItemAutoKey", transform="ref_product", sorento_field="product_ref", scope="line"),
            MappingWriteRow(source_path="Qty", transform="decimal", sorento_field="qty_ordered", scope="line"),
        ],
    )
    saved_rows = service.mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    rows = build_mapping_rows_for_run(
        ENTITY_SALES_ORDER, saved_rows, is_sql_db_source=True, source_config={},
    )
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_X",
    )
    raw = {
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open",
        "_lines": [
            {"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"},
            {"DtlKey": "L2", "ItemAutoKey": "P2", "Qty": "5"},
        ],
    }
    first = engine.map_document(raw)
    assert first.ok, [e.message() for e in first.errors]
    payload_first = first.record.sink_payload()
    assert len(payload_first["lines"]) == 2

    # Only line L1's qty changed - the SAME two lines must still be present.
    raw["_lines"][0]["Qty"] = "12"
    second = engine.map_document(raw)
    assert second.ok
    payload_second = second.record.sink_payload()
    assert len(payload_second["lines"]) == 2, (
        "a one-line change must still push the FULL line set, never a delta"
    )
    assert {l["source_ref"] for l in payload_second["lines"]} == {"AED_X:D1:L1", "AED_X:D1:L2"}
    db.close()


def test_picker_migration_idempotent(session_factory):
    """AC-02-05: the module migration's backfill function converts an
    existing task's `lineKeyColumn`/`lineProductColumn`/`lineWarehouseColumn`
    into three persisted line rows, once, idempotently, and strips the keys
    from `source_config`; `validate_source_config` no longer requires them.

    ASSUMED name: `modules.autocount.backfill.backfill_document_line_mapping_
    pickers(db, tenant_id, company_id, entity_type) -> int` (see module
    docstring) - not yet implemented, so this fails at import.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_MIG1", name="src")
    company = _company(db, conn.id, database="AED_MIG1", name="Mig Co")
    config = _document_config(
        db, company, conn.id,
        lineKeyColumn="dtl_key", lineProductColumn="item_code", lineWarehouseColumn=None,
    )

    from modules.autocount.backfill import backfill_document_line_mapping_pickers

    created = backfill_document_line_mapping_pickers(
        db, DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    )
    assert created == 2  # source_ref + product_ref (no warehouse column configured)

    line_rows = db.query(AcFieldMapping).filter(
        AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
        AcFieldMapping.company_id == company.id,
        AcFieldMapping.entity_type == ENTITY_SALES_ORDER,
        AcFieldMapping.scope == SCOPE_LINE,
    ).all()
    assert {r.canonical_field for r in line_rows} == {"source_ref", "product_ref"}

    db.refresh(config)
    for key in ("lineKeyColumn", "lineProductColumn", "lineWarehouseColumn"):
        assert key not in (config.source_config or {}), (
            f"'{key}' must be stripped from source_config by the backfill"
        )

    # Second call: idempotent, adds nothing more.
    again = backfill_document_line_mapping_pickers(
        db, DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    )
    assert again == 0

    # validate_source_config must no longer require the three picker keys.
    _, errors = validate_source_config(
        ENTITY_SALES_ORDER,
        {
            "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
        {"doc_key": "string", "doc_no": "string", "status": "string", "cancelled": "string",
         "doc_date": "date", "last_modified": "datetime"},
        line_columns={"dtl_key": "string", "item_code": "string"},
    )
    assert "lineKeyColumn" not in errors
    assert "lineProductColumn" not in errors
    db.close()


def test_line_result_columns_persist_and_gate(session_factory):
    """AC-02-06: a successful line-query preview at save time stores
    `line_result_columns` on the task, alongside `result_columns`; saving a
    line row whose column is absent from it is rejected ("Test the line
    query first").
    """
    assert hasattr(AcEntityConfig, "line_result_columns"), (
        "AcEntityConfig has no `line_result_columns` column yet (AC-02-06)"
    )

    import datetime as dt

    db = session_factory()
    engine = _source_engine_typed(
        [("D001", "SO-001", "open", "F", dt.date(2026, 8, 1), dt.datetime(2026, 8, 1, 9, 0, 0))],
        {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]},
    )
    conn = _sql_connection(db, engine, database="AED_LRC1", name="src")
    company = _company(db, conn.id, database="AED_LRC1", name="LRC Co")

    result = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {
            "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
            "lineKeyColumn": "dtl_key", "lineProductColumn": "item_code",
            "lineWarehouseColumn": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
    )
    line_result_columns = getattr(result, "line_result_columns", None)
    assert line_result_columns, (
        "EtlTaskView carries no `line_result_columns` after a successful line "
        "preview (AC-02-06)"
    )
    assert "dtl_key" in line_result_columns
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Group B - Status formula + line aggregates
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_STATUS_FORMULA = (
    'if(Cancelled == "T", "cancelled", if(lines.open_count == 0, "closed", "open"))'
)


def _aggregate_engine(status_formula: str = DEFAULT_STATUS_FORMULA) -> MappingEngine:
    rows = [
        MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
        MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
        MappingRow("Cancelled", "status", "string", SCOPE_HEADER, formula=status_formula),
        MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
        MappingRow("ItemAutoKey", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
        MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
        MappingRow("TransferedQty", "qty_delivered", "decimal", SCOPE_LINE),
    ]
    return MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_AGG",
    )


def test_line_aggregates_matrix(session_factory):
    """AC-02-07: `lines.count/open_count/ordered_sum/fulfilled_sum/
    outstanding_sum` are computed from the mapped lines of THAT header and
    available to the header's `status` formula; the formula catalog lists
    them for document entities.

    Today's gap: the formula language has exactly ONE named input (`value`
    - see `formula.py`'s `_KEYWORDS`); there is no cross-field/`lines.*`
    fact injection at all, so every formula below fails to evaluate (an
    unknown-name parse/runtime error), which the engine reports as a named
    field error - `mapped.ok` is False for every case.
    """
    engine = _aggregate_engine()
    matrix = [
        ("no lines", [], "closed"),
        ("all open", [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10", "TransferedQty": "0"}], "open"),
        ("all fulfilled", [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10", "TransferedQty": "10"}], "closed"),
        (
            "mixed",
            [
                {"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10", "TransferedQty": "10"},
                {"DtlKey": "L2", "ItemAutoKey": "P2", "Qty": "5", "TransferedQty": "0"},
            ],
            "open",
        ),
    ]
    for label, lines, expected in matrix:
        mapped = engine.map_document({
            "DocKey": f"D-{label}", "DocNo": "SO-1", "Cancelled": "F", "_lines": lines,
        })
        assert mapped.ok, f"{label}: {[e.message() for e in mapped.errors]}"
        assert mapped.record.status == expected, f"{label}: expected {expected}"

    # Cancelled always wins, regardless of line state.
    cancelled = engine.map_document({
        "DocKey": "D-cancelled", "DocNo": "SO-1", "Cancelled": "T",
        "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10", "TransferedQty": "0"}],
    })
    assert cancelled.ok
    assert cancelled.record.status == "cancelled"

    from modules.autocount.formula import catalog_payload

    payload = catalog_payload()
    variables = payload.get("variables") or []
    var_names = {v.get("name") if isinstance(v, dict) else v for v in variables}
    assert {"lines.count", "lines.open_count", "lines.ordered_sum",
            "lines.fulfilled_sum", "lines.outstanding_sum"} <= var_names, (
        "the formula catalog does not list the line aggregates as variables (AC-02-07)"
    )


def test_default_status_formula_and_vocabulary(session_factory):
    """AC-02-08: a preset-born SO task's `status` row formula equals the
    documented default; a PUT with a status-formula literal outside the
    vocabulary is rejected (422); the vocabulary stays the fixed five words.
    """
    assert set(DOCUMENT_STATUS_VALUES) == {
        "open", "partial", "fulfilled", "closed", "cancelled",
    }

    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_VOCAB1", name="src")
    company = _company(db, conn.id, database="AED_VOCAB1", name="Vocab Co")
    _document_config(db, company, conn.id)
    service = CompanyService(db)

    # `so_number` is included so the ONLY reason this can fail is the
    # vocabulary-literal guard under test - not the pre-existing "required
    # field unmapped" guard.
    with pytest.raises(AutocountServiceError):
        service.replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
            [
                MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
                MappingWriteRow(
                    source_path="Cancelled", transform="string", sorento_field="status",
                    # "shipped" is not in DOCUMENT_STATUS_VALUES - a literal
                    # outside the vocabulary must be rejected at save time
                    # (AC-02-08). Written with TODAY's single-`value` formula
                    # grammar (not a named `Cancelled` reference) so the ONLY
                    # thing that can make this raise is the vocabulary check
                    # itself - `parse_formula` alone already accepts this
                    # (it is syntactically valid), so `replace_mapping`
                    # currently saves it clean: no vocabulary awareness
                    # exists yet.
                    formula='if(value == "T", "cancelled", "shipped")',
                ),
            ],
        )
    db.close()


def test_formula_functions():
    """AC-02-09: `startswith`, `upper`, `trim`, `coalesce` all evaluate
    (`not` already works as the unary operator). `upper`/`trim` already
    exist server-side; `startswith`/`coalesce` do not - `parse_formula`
    raises `FormulaParseError` for both today."""
    from modules.autocount.formula import evaluate_formula, result_to_json

    assert result_to_json(evaluate_formula("upper(value)", "so-1")) == "SO-1"
    assert result_to_json(evaluate_formula("trim(value)", "  so-1  ")) == "so-1"
    assert result_to_json(evaluate_formula('not(startswith(value, "SPO-"))', "PO-1")) is True
    assert result_to_json(evaluate_formula('coalesce(value, "CNY")', None)) == "CNY"


def test_default_never_partial(session_factory):
    """AC-02-15: the default status formula never yields `partial` across a
    full matrix of Cancelled x delivered/ordered combinations."""
    engine = _aggregate_engine()
    for cancelled in ("T", "F"):
        for delivered in ("0", "5", "10"):
            mapped = engine.map_document({
                "DocKey": f"D-{cancelled}-{delivered}", "DocNo": "SO-1", "Cancelled": cancelled,
                "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10", "TransferedQty": delivered}],
            })
            assert mapped.ok, [e.message() for e in mapped.errors]
            assert mapped.record.status != "partial"


# ═══════════════════════════════════════════════════════════════════════════
# Group C - Shipping orders
# ═══════════════════════════════════════════════════════════════════════════


def test_shipping_order_entity():
    """AC-02-10: `ENTITY_SHIPPING_ORDER` registered sql_db-only, document
    profile, `CanonicalShippingOrder`(+line), sink path `shipping_orders`,
    in `_DEPENDENT_ENTITIES` and the ten-entity DB-company add-entity set;
    a null header `entity_id` with line results is a SUCCESS (line-set
    entity, addendum section 3), never a failure."""
    from modules.autocount.canonical.documents import (
        ENTITY_SHIPPING_ORDER,
        CanonicalShippingOrder,
        CanonicalShippingOrderLine,
    )

    assert ENTITY_SHIPPING_ORDER == "shipping_order"
    assert ENTITY_SHIPPING_ORDER in ENTITY_PROFILES
    assert ENTITY_PROFILES[ENTITY_SHIPPING_ORDER].line_model is CanonicalShippingOrderLine
    assert ENTITY_SHIPPING_ORDER in ETL_ENTITY_TYPES

    from modules.autocount.sinks_sorento import _DEPENDENT_ENTITIES, _ENTITY_PATH

    assert _ENTITY_PATH.get(ENTITY_SHIPPING_ORDER) == "shipping_orders"
    assert ENTITY_SHIPPING_ORDER in _DEPENDENT_ENTITIES
    assert sorento_supports_entity(ENTITY_SHIPPING_ORDER)

    rec = CanonicalShippingOrder(
        source_ref="x", spo_number="SPO-1", status="open",
        lines=[CanonicalShippingOrderLine(source_ref="x:L1", product_ref="p1", qty_ordered=Decimal("5"))],
    )
    payload = rec.sink_payload()
    assert payload["source_ref"] == "x"
    assert len(payload["lines"]) == 1

    # DB company add-entity set: ten entities (nine today + shipping_order).
    assert len(set(ENTITY_PROFILES) - {"goods_received_note"}) == 10


def test_filter_formula_skips_headers(session_factory):
    """AC-02-11: a document task's `source_config.filterFormula` skips a
    header before line fetch when it evaluates false - never staged, never a
    delete candidate, and the run counts it (`skipped_by_filter`); the PO/SPO
    presets filter is the documented `startswith`/`not(startswith(...))`
    string.
    """
    engine = _source_engine(
        [
            ("D001", "PO-001", "open", "F", "2026-08-01", "2026-08-01 09:00:00"),
            ("D002", "SPO-001", "open", "F", "2026-08-02", "2026-08-02 09:00:00"),
        ],
        {"D001": [("D001-1", "ITEM-A", "10", "0", 1)], "D002": [("D002-1", "ITEM-B", "5", "0", 1)]},
    )
    db = session_factory()
    conn = _sql_connection(db, engine, database="AED_FILT1", name="src")
    company = _company(db, conn.id, database="AED_FILT1", name="Filter Co")
    config = _document_config(
        db, company, conn.id, entity_type=ENTITY_PURCHASE_ORDER,
        filterFormula='not(startswith(upper(trim(DocNo)), "SPO-"))',
    )

    clean, errors = validate_source_config(
        ENTITY_PURCHASE_ORDER,
        config.source_config,
        {"doc_key": "string", "doc_no": "string", "status": "string", "cancelled": "string",
         "doc_date": "date", "last_modified": "datetime"},
        line_columns={"dtl_key": "string", "item_code": "string"},
    )
    assert clean.get("filterFormula") == 'not(startswith(upper(trim(DocNo)), "SPO-"))', (
        "validate_source_config drops filterFormula (AC-02-11 not wired yet)"
    )

    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_PURCHASE_ORDER)
    result = source.fetch_changes(Watermark())
    refs = {r.raw.get("doc_no") for r in result.records}
    assert "SPO-001" not in refs, "the SPO-numbered header must be filtered OUT of a PO task"
    assert result.skipped_by_filter == 1, (
        "FetchResult carries no `skipped_by_filter` count yet (AC-02-11)"
    )
    db.close()


def test_overlap_warning(session_factory):
    """AC-02-12: a PO task and a SPO task on one company - the activation
    preview of one reports a header staged by the OTHER in its last run as
    `warnings.overlapping_documents`, non-blocking.

    Blocked on AC-02-10 (`ENTITY_SHIPPING_ORDER` does not exist yet) - fails
    at import, which is the honest reason this AC cannot be exercised until
    shipping orders are registered.
    """
    from modules.autocount.canonical.documents import ENTITY_SHIPPING_ORDER  # noqa: F401

    db = session_factory()
    engine = _source_engine(
        [("D001", "PO-001", "open", "F", "2026-08-01", "2026-08-01 09:00:00")],
        {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]},
    )
    conn = _sql_connection(db, engine, database="AED_OVL1", name="src")
    company = _company(db, conn.id, database="AED_OVL1", name="Overlap Co")
    _document_config(db, company, conn.id, entity_type=ENTITY_PURCHASE_ORDER)
    _document_config(db, company, conn.id, entity_type=ENTITY_SHIPPING_ORDER)

    # A prior PO run staged D001; the SPO task's activation preview should
    # warn that D001 is "owned" by the sibling PO task.
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, {"AED_OVL1:D001": "h1"},
        seen_at=None,
    )
    db.commit()

    _, preview = EtlService(db).preview_task(DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER)
    warnings = preview.get("warnings") or {}
    assert warnings.get("overlappingDocuments"), (
        "the activation preview carries no overlap warning yet (AC-02-12)"
    )
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Group D - Deletes + fallback fields
# ═══════════════════════════════════════════════════════════════════════════


def test_document_deletes_propagate(session_factory):
    """AC-02-13: a reconcile run with an absent known header stages a delete
    intent (the "documents skip deletes" branch from plan-22 is removed);
    the delete guard (> max(20%, 50)) still applies; a present header with
    Cancelled='T' is never a delete candidate (a status update instead).
    """
    header_rows = [
        (f"D{n:03d}", f"SO-{n:03d}", "open", "F", "2026-08-01", "2026-08-01 09:00:00")
        for n in range(1, 61)
    ]
    lines = {row[0]: [(f"{row[0]}-1", "ITEM-A", "10", "0", 1)] for row in header_rows}
    db = session_factory()
    engine = _source_engine(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_DEL1", name="src")
    company = _company(db, conn.id, database="AED_DEL1", name="Del Co")
    config = _document_config(db, company, conn.id)

    # Seed 60 previously-known header hashes; the extract below returns only
    # the first 5 (55 "missing" - over both the 20% ratio and the absolute
    # floor of 50), so the guard must fire.
    known = {f"AED_DEL1:D{n:03d}": "h" for n in range(1, 61)}
    RowHashRepository(db).upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, known, seen_at=None)
    db.commit()

    with engine.begin() as conn_raw:
        conn_raw.exec_driver_sql("DELETE FROM so_header WHERE doc_key NOT IN "
                                  "('D001','D002','D003','D004','D005')")

    source = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER, mode=RUN_MODE_RECONCILE,
    )
    with pytest.raises(SqlDeleteGuardExceeded):
        source.fetch_changes(Watermark())
    db.close()


def test_document_deletes_propagate_below_guard_and_status_update(session_factory):
    """The companion case: ONE missing header (well under the guard) must
    surface as a delete intent, and a PRESENT header (even Cancelled='T')
    must never be one - staged via `sync._stage_deletes`, which today
    short-circuits every document entity to "drop the local hash row only"
    (never stages an `AcStagedRecord`)."""
    from modules.autocount import sync as sync_module

    header_rows = [
        ("D001", "SO-001", "open", "F", "2026-08-01", "2026-08-01 09:00:00"),
        ("D002", "SO-002", "open", "T", "2026-08-02", "2026-08-02 09:00:00"),
    ]
    lines = {
        "D001": [("D001-1", "ITEM-A", "10", "0", 1)],
        "D002": [("D002-1", "ITEM-B", "5", "5", 1)],
    }
    db = session_factory()
    engine = _source_engine(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_DEL2", name="src")
    company = _company(db, conn.id, database="AED_DEL2", name="Del Co 2")
    config = _document_config(db, company, conn.id)

    known = {"AED_DEL2:D001": "h1", "AED_DEL2:D002": "h2", "AED_DEL2:D003": "h3"}
    RowHashRepository(db).upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, known, seen_at=None)
    db.commit()

    source = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER, mode=RUN_MODE_RECONCILE,
    )
    result = source.fetch_changes(Watermark())
    assert "AED_DEL2:D003" in result.delete_refs, (
        "a header missing from the extract must be a delete candidate for a "
        "document entity too (AC-02-13) - today `not self.is_document` "
        "excludes it entirely"
    )
    assert "AED_DEL2:D001" not in result.delete_refs
    assert "AED_DEL2:D002" not in result.delete_refs  # present, Cancelled='T' -> status update

    job = types.SimpleNamespace(id="job-del-1")
    staged = sync_module._stage_deletes(
        db, job, result.delete_refs,
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        current_refs=result.current_refs,
    )
    assert staged == 1, "a document delete intent must actually be staged now"
    row = db.query(AcStagedRecord).filter(
        AcStagedRecord.entity_type == ENTITY_SALES_ORDER,
        AcStagedRecord.op == STAGED_OP_DELETE,
    ).first()
    assert row is not None and row.status == STAGED
    db.close()


def test_shipping_order_deletions_404_unknown_entity_is_retryable():
    """AC-02-13: a `shipping_orders` 404 UNKNOWN_ENTITY from `/deletions`
    maps to retryable, not a raised batch-level error."""
    from modules.autocount.canonical.documents import ENTITY_SHIPPING_ORDER  # not yet -> ImportError

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "UNKNOWN_ENTITY", "message": "not yet supported"})

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type=ENTITY_SHIPPING_ORDER,
        transport=httpx.MockTransport(handle),
    )
    result = sink.delete_batch(["ref-1"])
    assert result["summary"].get("retryable", 0) >= 1, (
        "a 404 UNKNOWN_ENTITY from /deletions must be retryable, not raised"
    )


def test_sink_payload_contract_gate():
    """AC-02-14/27: `sink_payload(contract_version=1)` omits the fallback +
    `line_number` fields; version 2 includes them. The connection config
    `sorento_contract_version` (default 1) is the AUTHORITATIVE gate - an
    advertised higher version never auto-flips the payload.
    """
    rec = CanonicalSalesOrder(
        source_ref="x", so_number="SO-1", status="open", customer_code="C001",
        customer_name="Acme", agent_code="SA01",
        lines=[
            CanonicalSalesOrderLine(
                source_ref="x:L1", product_ref="p1", qty_ordered=Decimal("1"),
                product_code="ITEM-A", product_name="Widget", warehouse_code="WH1",
            )
        ],
    )
    # `sink_payload()` takes NO arguments today - `contract_version` does not
    # exist yet (AC-02-14), so this call raises `TypeError` right now. Once
    # implemented, v1 must OMIT the fallback fields and v2 must include them.
    payload_v1 = rec.sink_payload(contract_version=1)
    assert "customer_code" not in payload_v1
    assert "customer_name" not in payload_v1
    assert "agent_code" not in payload_v1
    assert "product_code" not in payload_v1["lines"][0]
    assert "warehouse_code" not in payload_v1["lines"][0]

    payload_v2 = rec.sink_payload(contract_version=2)
    assert payload_v2["customer_code"] == "C001"
    assert payload_v2["customer_name"] == "Acme"
    assert payload_v2["agent_code"] == "SA01"
    assert payload_v2["lines"][0]["product_code"] == "ITEM-A"
    assert payload_v2["lines"][0]["warehouse_code"] == "WH1"


def test_contract_version_mismatch_is_advisory_only(session_factory):
    """AC-02-14: `GET /api/v1/external/contract` advertising a higher
    version than the connection's `sorento_contract_version` setting yields
    `warnings.contract_version_mismatch` in the activation preview and never
    auto-flips the payload."""
    db = session_factory()
    engine = _source_engine(
        [("D001", "SO-001", "open", "F", "2026-08-01", "2026-08-01 09:00:00")],
        {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]},
    )
    conn = _sql_connection(db, engine, database="AED_CV1", name="src")
    company = _company(db, conn.id, database="AED_CV1", name="CV Co")
    _document_config(db, company, conn.id)

    consumer = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="consumer", name="Sorento",
        config_json={"baseUrl": "http://sorento.example.com", "sorentoContractVersion": 1},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add(consumer)
    db.commit()
    db.refresh(consumer)
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl="sorento", sink_connection_id=consumer.id,
        sorento_company_code="CO1",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contract"):
            return httpx.Response(200, json={"version": 2})
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 1, "updated": 0, "failed": 0, "retryable": 0},
            "records": [{"source_ref": "AED_CV1:D001", "outcome": "created", "entity_id": "id-1"}],
        })

    from modules.autocount import sinks_sorento as sinks_module

    original_from_connection = sinks_module.sorento_sink_from_connection

    def patched(config, credentials, *, entity_type, company_code):
        sink = original_from_connection(config, credentials, entity_type=entity_type, company_code=company_code)
        sink._transport = httpx.MockTransport(handle)  # type: ignore[attr-defined]
        return sink

    import modules.autocount.services.company_service as company_service_module
    company_service_module.sorento_sink_from_connection = patched
    try:
        _, preview = EtlService(db).preview_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    finally:
        company_service_module.sorento_sink_from_connection = original_from_connection

    warnings = preview.get("warnings") or {}
    assert warnings.get("contractVersionMismatch"), (
        "no advisory contract-version-mismatch warning surfaces yet (AC-02-14)"
    )
    db.close()


def test_simulate_with_lines(session_factory):
    """AC-02-22: `POST .../mapping/simulate {record, rows, lines}` returns
    `headerFields`, `lineFields[]`, `status`, and the exact Sorento payload
    at the current contract version; `line_number` present at v2, absent at
    v1.

    Today's gap: `CompanyService.simulate_mapping` has no `lines` parameter
    at all.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_SIM1", name="src")
    company = _company(db, conn.id, database="AED_SIM1", name="Sim Co")
    _document_config(db, company, conn.id)

    service = CompanyService(db)
    # `simulate_mapping` has no `lines` parameter today - this raises
    # `TypeError` right now. Once implemented it must run header + line
    # mapping/formulas and surface `status` + `lineFields`.
    result = service.simulate_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {"DocNo": "SO-1", "Cancelled": "F"},
        None,
        lines=[{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"}],
    )
    assert result.get("lineFields")
    assert "status" in result
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Group E - Presets
# ═══════════════════════════════════════════════════════════════════════════


def test_preset_seed_on_first_save(session_factory):
    """AC-02-16: the first task save for SO/PO/SPO on a DB company, with an
    empty mapping, seeds the documented header+line rows from the AutoCount
    preset; a row whose source column is missing from the query's result
    columns is seeded `is_enabled=false`; rows are ordinary editable rows;
    a second save does not re-seed.

    Today's gap: `EtlService.update_task` never seeds ANY mapping rows for a
    document entity - `CompanyService._seed_mapping_rows`/`seed_company_
    defaults` only run for `SEEDED_ENTITIES` (GRN/supplier/customer).
    """
    import datetime as dt

    header_rows = [
        ("D001", "SO-001", "open", "F", dt.date(2026, 8, 1), dt.datetime(2026, 8, 1, 9, 0, 0))
    ]
    lines = {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]}
    db = session_factory()
    # This header query OMITS `SalesAgent`-equivalent so the seeded
    # `sales_agent_ref` row must land disabled (no such column here at all -
    # the query never carries one, matching "column not in query").
    engine = _source_engine_typed(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_PRESET1", name="src")
    company = _company(db, conn.id, database="AED_PRESET1", name="Preset Co")

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {
            "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
            "lineKeyColumn": "dtl_key", "lineProductColumn": "item_code",
            "lineWarehouseColumn": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
    )

    rows = CompanyService(db).mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    assert rows, (
        "the first save of an empty document mapping seeds nothing yet (AC-02-16)"
    )
    by_field = {r.canonical_field: r for r in rows}
    assert "so_number" in by_field
    assert "status" in by_field and by_field["status"].formula == DEFAULT_STATUS_FORMULA
    assert any(f in by_field for f in ("source_ref",)), "line rows must be seeded too"

    # Second save must NOT duplicate the seeded rows.
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {
            "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
            "lineKeyColumn": "dtl_key", "lineProductColumn": "item_code",
            "lineWarehouseColumn": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
    )
    rows_again = CompanyService(db).mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    assert len(rows_again) == len(rows), "a second save must not re-seed"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Group G - full suite green (AC-02-24)
# ═══════════════════════════════════════════════════════════════════════════


def test_existing_autocount_suite_still_green_reference():
    """AC-02-24 (partial pin): the entities this slice touches keep working
    for the API-path / non-document cases the rest of `test_autocount*`
    exercises - a smoke check that a plain master profile is untouched by
    the S2/S3 line-scope changes."""
    profile = flat_profile("customer", ["AccNo"])
    assert profile.line_model is None
    assert profile.line_ref_prefix is False


# ═══════════════════════════════════════════════════════════════════════════
# Group H - security-review round (findings F1-F3), RED tests written before
# the coder sees them.
# ═══════════════════════════════════════════════════════════════════════════


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_narrowing_source_config_rebaselines_row_hashes(session_factory):
    """F1 (BLOCKER): narrowing a live document task's population-defining
    `source_config` (here: `fromDate` moved forward) must RE-BASELINE the
    task's row-hash rows, never leave them stale to manufacture phantom
    deletes.

    Today's gap: `EtlService.update_task` clears `last_preview_at` /
    `last_preview_failed_count` on every save but never touches
    `RowHashRepository` - a header that falls out of the new scope (still
    exists in AutoCount, just outside the new `fromDate` floor) stays in the
    OLD hash population, so the next full-extract reconcile's `known -
    current_refs` diff reads its absence from THIS run's narrower window as a
    genuine deletion and stages a delete intent nobody asked for.
    """
    import datetime as dt

    header_rows = [
        ("D001", "SO-001", "open", "F", dt.date(2026, 1, 10), dt.datetime(2026, 1, 10, 9, 0, 0)),
        ("D002", "SO-002", "open", "F", dt.date(2026, 2, 10), dt.datetime(2026, 2, 10, 9, 0, 0)),
        ("D003", "SO-003", "open", "F", dt.date(2026, 3, 10), dt.datetime(2026, 3, 10, 9, 0, 0)),
    ]
    lines = {
        "D001": [("D001-1", "ITEM-A", "10", "0", 1)],
        "D002": [("D002-1", "ITEM-A", "10", "0", 1)],
        "D003": [("D003-1", "ITEM-A", "10", "0", 1)],
    }
    db = session_factory()
    engine = _source_engine_typed(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_F1A", name="src")
    company = _company(db, conn.id, database="AED_F1A", name="F1 Co A")

    base_payload = {
        "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
        "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
        "comparedColumns": [], "docDateColumn": "doc_date",
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }

    service = EtlService(db)
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {**base_payload, "fromDate": "2026-01-01"},
    )

    # Simulate an ACTIVE task with a standing hash population from prior runs
    # (all three headers previously seen and reconciled).
    known = {"AED_F1A:D001": "h1", "AED_F1A:D002": "h2", "AED_F1A:D003": "h3"}
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, known, seen_at=None
    )
    db.commit()
    assert RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    ) == known

    # Narrow the population: fromDate moves forward past D001.
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {**base_payload, "fromDate": "2026-02-01"},
    )

    remaining = RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    )
    assert remaining == {}, (
        "narrowing a population-defining source_config key must clear this "
        f"entity's row-hash rows so the next reconcile re-baselines instead "
        f"of manufacturing deletes for out-of-scope headers - got {remaining}"
    )

    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_SALES_ORDER,
        )
        .one()
    )
    source = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER, mode=RUN_MODE_RECONCILE,
    )
    result = source.fetch_changes(Watermark())
    assert result.delete_refs == [], (
        "a header that merely fell outside the new fromDate scope (D001) must "
        f"never be staged as a delete intent - got {result.delete_refs}"
    )
    refs = {r.raw.get("doc_key") for r in result.records}
    assert refs == {"D002", "D003"}, f"unexpected in-scope headers: {refs}"
    assert result.added_count == 2, (
        "with the hash population re-baselined, both still-present headers "
        f"must stage as ADDS, not (falsely) as updates - got added={result.added_count}"
    )
    db.close()


def test_schedule_only_save_keeps_row_hashes(session_factory):
    """Control for F1: a save that changes ONLY schedule fields (never a
    population-defining key: connection/query/lineQuery/keyColumns/
    watermarkColumn/fromDate/filterFormula) must NOT clear the task's
    row-hash rows - pairs with the mutation test above so a coder cannot
    satisfy F1 by clearing hashes on every save unconditionally."""
    import datetime as dt

    header_rows = [
        ("D001", "SO-001", "open", "F", dt.date(2026, 1, 10), dt.datetime(2026, 1, 10, 9, 0, 0)),
    ]
    lines = {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]}
    db = session_factory()
    engine = _source_engine_typed(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_F1B", name="src")
    company = _company(db, conn.id, database="AED_F1B", name="F1 Co B")

    base_payload = {
        "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
        "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
        "comparedColumns": [], "docDateColumn": "doc_date", "fromDate": "2026-01-01",
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, base_payload)

    known = {"AED_F1B:D001": "h1"}
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, known, seen_at=None
    )
    db.commit()

    # Re-save with ONLY the schedule changed - no population-defining key moved.
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        {
            **base_payload,
            "incrementalMinutes": 30,
            "reconcileMode": "interval",
            "reconcileHours": 4,
        },
    )

    remaining = RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    )
    assert remaining == known, (
        "a schedule-only save must never clear row-hash rows (only "
        f"population-defining keys should) - got {remaining}"
    )
    db.close()


def test_update_task_rejects_unparseable_filter_formula(session_factory):
    """F2 (should-fix): `validate_source_config` must reject an unparseable
    `filterFormula` at PUT time with a field error on `filterFormula` (422).
    `formula.py`'s own `evaluate_row_filter` docstring already promises this
    ("a bad formula is instead caught at PUT-time by
    `validate_source_config`'s own parse check") but `validate_source_config`
    never calls into the formula parser at all today - it only strips
    whitespace, so a formula that will fail to parse at EVERY run instead
    saves clean and silently fails OPEN (every header kept) forever.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_F2A", name="src")
    company = _company(db, conn.id, database="AED_F2A", name="F2 Co A")
    config = _document_config(
        db, company, conn.id, entity_type=ENTITY_PURCHASE_ORDER,
        filterFormula='startswith(upper(trim(DocNo)), "SPO-"',  # missing ')'
    )

    _clean, errors = validate_source_config(
        ENTITY_PURCHASE_ORDER,
        config.source_config,
        {"doc_key": "string", "doc_no": "string", "status": "string",
         "cancelled": "string", "doc_date": "date", "last_modified": "datetime"},
        line_columns={"dtl_key": "string", "item_code": "string"},
    )
    assert "filterFormula" in errors, (
        "an unparseable filterFormula must be rejected with a field error at "
        f"save time - got errors={errors}"
    )


def test_update_task_rejects_filter_formula_unknown_variable(session_factory):
    """F2: a `filterFormula` referencing a name that is not in the saved
    header `result_columns` must be a save-time 422 on `filterFormula`, not
    silently accepted (and then fail OPEN - every header kept - at every run
    since the name never resolves against any real row)."""
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_F2B", name="src")
    company = _company(db, conn.id, database="AED_F2B", name="F2 Co B")
    config = _document_config(
        db, company, conn.id, entity_type=ENTITY_PURCHASE_ORDER,
        filterFormula='startswith(upper(trim(NotAColumnAtAll)), "SPO-")',
    )

    _clean, errors = validate_source_config(
        ENTITY_PURCHASE_ORDER,
        config.source_config,
        {"doc_key": "string", "doc_no": "string", "status": "string",
         "cancelled": "string", "doc_date": "date", "last_modified": "datetime"},
        line_columns={"dtl_key": "string", "item_code": "string"},
    )
    assert "filterFormula" in errors, (
        "a filterFormula referencing a variable outside the saved header "
        f"result_columns must be rejected - got errors={errors}"
    )


def test_update_task_accepts_valid_filter_formula(session_factory):
    """Control for F2: a `filterFormula` that parses clean against the
    header's own result_columns (fold-matched exactly like
    `evaluate_row_filter` already matches at run time - `DocNo` against a
    `doc_no` result column) must still save with NO `filterFormula` error -
    the new parse gate must not reject the exact convention the PO/SPO
    presets already ship (`presets.py` `_PO_FILTER_FORMULA`)."""
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_F2C", name="src")
    company = _company(db, conn.id, database="AED_F2C", name="F2 Co C")
    config = _document_config(
        db, company, conn.id, entity_type=ENTITY_PURCHASE_ORDER,
        filterFormula='not(startswith(upper(trim(DocNo)), "SPO-"))',
    )

    _clean, errors = validate_source_config(
        ENTITY_PURCHASE_ORDER,
        config.source_config,
        {"doc_key": "string", "doc_no": "string", "status": "string",
         "cancelled": "string", "doc_date": "date", "last_modified": "datetime"},
        line_columns={"dtl_key": "string", "item_code": "string"},
    )
    assert "filterFormula" not in errors, (
        "a legitimate filterFormula referencing a real header column "
        f"(case/format-folded) must not be rejected - got errors={errors}"
    )


def test_simulate_accepts_default_status_formula_and_line_formula(client, session_factory):
    """F3 (should-fix): Simulate must accept ANY formula the save gate
    (`CompanyService.replace_mapping`) accepts.

    Today's gap: `_draft_engine_rows`/`_draft_engine_rows_for_scope` call
    `parse_formula` with `known_vars=None` for BOTH header and line drafts -
    unlike `replace_mapping`, which builds `known_vars` from
    `config.result_columns` / `config.line_result_columns` (+
    `LINE_AGGREGATE_NAMES` for the header) - so a draft header row carrying
    the seeded `DEFAULT_STATUS_FORMULA` (`Cancelled`, `lines.open_count`) or a
    draft line row referencing a line column both 422 "Unknown name" at
    Simulate even though the identical row would save cleanly via PUT
    mapping.
    """
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database="AED_F3A", name="src")
    company = _company(db, conn.id, database="AED_F3A", name="F3 Co")
    config = _document_config(db, company, conn.id, entity_type=ENTITY_SALES_ORDER)
    # Match a real preset's PascalCase result columns - what the default
    # status formula's `Cancelled` reference resolves against, and what
    # `replace_mapping` would build `known_vars` from for this task.
    config.result_columns = ["DocKey", "DocNo", "Status", "Cancelled", "DocDate", "LastModified"]
    config.line_result_columns = ["DtlKey", "ItemAutoKey", "Qty", "TransferedQty"]
    db.add(config)
    db.commit()
    company_id = company.id
    db.close()

    headers = _auth(client)
    response = client.post(
        f"/autocount/companies/{company_id}/entities/{ENTITY_SALES_ORDER}/mapping/simulate",
        headers=headers,
        json={
            "record": {
                "DocKey": "D001", "DocNo": "SO-001", "Status": "open", "Cancelled": "F",
            },
            "rows": [
                {
                    "sourcePath": "Cancelled", "transform": "string", "sorentoField": "status",
                    "formula": DEFAULT_STATUS_FORMULA, "scope": "header",
                },
                {
                    "sourcePath": "TransferedQty", "transform": "decimal",
                    "sorentoField": "qty_ordered",
                    "formula": 'if(TransferedQty == "0", 0, 1)', "scope": "line",
                },
            ],
            "lines": [{"ItemAutoKey": "P1", "TransferedQty": "0"}],
        },
    )
    assert response.status_code == 200, (
        "Simulate must accept a formula the save gate would accept (same "
        f"known-variable set as replace_mapping) - got {response.status_code}: "
        f"{response.text}"
    )
