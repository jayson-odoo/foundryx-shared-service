"""AutoCount bulk document load - round 4 (plan sprint-5/03), at HEAD f01ce40.

URGENT (live-load finding): a live load pushed 5,000 real sales orders whose
staged ``raw_json`` carried no ``_lines`` key and whose ``canonical_json
["lines"]`` was empty, even though every header had ``LineCount > 0``. The
paged path (``SqlDbSource.fetch_page``) never called ``_read_lines`` for a
new header IN A WAY THAT SURVIVED - it built each ``SourceRecord.raw`` via
``json_safe(header)`` (a snapshot dict comprehension, not a live reference)
BEFORE the later ``if self.is_document and changed_headers: ... header
[SQL_DOC_LINES_KEY] = self._read_lines(...)`` loop mutates the SAME
``header`` dict - the snapshot already taken never sees the lines attached
after it.

Second item: a header row carrying a ``LineCount`` fingerprint column (the
preset pack's own change-detection aggregate) with a value greater than zero,
whose line fetch comes back with zero rows, must be staged FAILED naming the
mismatch - never silently accepted as a valid, lineless document. Not yet
implemented anywhere (grepped clean) - this is a new guard the coder must
add, not a regression pin.

Both driven through the REAL paged run (``run_autocount_sync`` via
``JobService.create_and_enqueue``, eager under tests), never by calling
``fetch_page``/``_stage_documents`` directly - a live scheduled run is
exactly this entry point.

Reuses ``tests/test_autocount_document_mapping.py``'s document-rig helpers
(``_source_engine``, ``_sql_connection``, ``_company``, ``_document_config``)
for the first test - cross-test-file imports are an established pattern in
this suite. The second test builds its own tiny engine/config inline (needs
a ``LineCount`` column the shared rig's fixed schema does not have).
"""
from __future__ import annotations

from typing import Dict, List

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.models import (
    RUN_SUCCESS,
    STAGED,
    STAGED_FAILED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
    AcSyncRun,
    SOURCE_IMPL_SQL_DB,
)
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sync import AUTOCOUNT_SYNC

from tests.test_autocount_document_mapping import (
    _company,
    _document_config,
    _source_engine,
    _sql_connection,
)


def _seed_row(
    db, company, *, scope: str, source_path: str, canonical_field: str,
    transform: str, required: bool = False,
) -> AcFieldMapping:
    row = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID,
        company_id=company.id,
        entity_type=ENTITY_SALES_ORDER,
        scope=scope,
        source_path=source_path,
        canonical_field=canonical_field,
        transform=transform,
        is_required=required,
        is_enabled=True,
    )
    db.add(row)
    return row


def test_a_paged_document_run_carries_its_own_lines_into_raw_and_canonical_json(
    session_factory,
):
    header_rows = [
        ("D001", "SO-001", "open", "F", "2026-08-01", "2026-08-01 09:00:00"),
        ("D002", "SO-002", "open", "F", "2026-08-02", "2026-08-02 09:00:00"),
        ("D003", "SO-003", "open", "F", "2026-08-03", "2026-08-03 09:00:00"),
    ]
    lines: Dict[str, List[tuple]] = {
        "D001": [("D001-1", "ITEM-A", "10", "0", 1), ("D001-2", "ITEM-B", "5", "0", 2)],
        "D002": [("D002-1", "ITEM-A", "10", "0", 1), ("D002-2", "ITEM-B", "5", "0", 2)],
        "D003": [("D003-1", "ITEM-A", "10", "0", 1), ("D003-2", "ITEM-B", "5", "0", 2)],
    }
    db = session_factory()
    engine = _source_engine(header_rows, lines)
    conn = _sql_connection(db, engine, database="AED_R4A", name="src")
    company = _company(db, conn.id, database="AED_R4A", name="R4A Co")
    _document_config(db, company, conn.id, entity_type=ENTITY_SALES_ORDER)

    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="doc_no",
        canonical_field="so_number", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="status",
        canonical_field="status", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="dtl_key",
        canonical_field="source_ref", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="item_code",
        canonical_field="product_ref", transform="ref_product", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="qty_ordered",
        canonical_field="qty_ordered", transform="decimal", required=True,
    )
    db.commit()

    statements = {"header": 0, "line": 0}

    def before_cursor_execute(conn2, cursor, statement, parameters, context, executemany):
        low = statement.lower()
        if "so_header" in low:
            statements["header"] += 1
        if "so_line" in low:
            statements["line"] += 1

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        job = JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={
                "companyId": company.id, "entityType": ENTITY_SALES_ORDER,
                "mode": "manual",
            },
        )

        run = db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()
        assert run.outcome == RUN_SUCCESS, f"outcome={run.outcome!r} error={run.error!r}"

        staged = (
            db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
                AcStagedRecord.company_id == company.id,
                AcStagedRecord.entity_type == ENTITY_SALES_ORDER,
            )
            .all()
        )
        assert len(staged) == 3, (
            f"expected 3 staged headers, got {len(staged)} "
            f"(statuses={[s.status for s in staged]}, "
            f"errors={[s.error for s in staged]})"
        )
        for record in staged:
            assert record.status == STAGED, (
                f"{record.source_ref}: expected STAGED, got {record.status!r} "
                f"({record.error!r})"
            )
            assert "_lines" in record.raw_json, (
                f"{record.source_ref}: raw_json is missing '_lines' entirely - "
                f"keys={sorted(record.raw_json.keys())}"
            )
            assert len(record.raw_json["_lines"]) == 2, (
                f"{record.source_ref}: raw_json['_lines'] has "
                f"{len(record.raw_json.get('_lines') or [])} entries, expected 2"
            )
            assert len(record.canonical_json.get("lines") or []) == 2, (
                f"{record.source_ref}: canonical_json['lines'] has "
                f"{len(record.canonical_json.get('lines') or [])} entries, "
                f"expected 2"
            )

        # One line statement per CHANGED header (3 new headers this run),
        # never a batched/shared statement and never zero.
        assert statements["line"] == 3, (
            f"expected exactly 3 line statements (one per changed header) - "
            f"got {statements['line']}"
        )

        # A second run (RECONCILE - a full re-extract) with nothing changed
        # at source must find every header UNCHANGED and fetch NO lines at
        # all (lines are only ever fetched for changed/new headers).
        statements["line"] = 0
        job2 = JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={
                "companyId": company.id, "entityType": ENTITY_SALES_ORDER,
                "mode": "reconcile",
            },
        )
        run2 = db.query(AcSyncRun).filter(AcSyncRun.job_id == job2.id).one()
        assert run2.outcome == RUN_SUCCESS, f"outcome={run2.outcome!r} error={run2.error!r}"
        assert statements["line"] == 0, (
            f"an unchanged header must never be re-fetched for lines - got "
            f"{statements['line']} line statement(s) on the reconcile pass"
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    db.close()
    RUNTIME.dispose_all()


# ── LineCount fingerprint mismatch (round 4, second item) ──────────────────


def _line_count_rig(session_factory):
    """A tiny, self-contained document rig whose header query carries a
    ``LineCount`` column (the preset pack's own change-detection aggregate,
    ``presets.py``'s ``SO_PRESET``/``PO_PRESET`` both select one) - the
    shared ``test_autocount_document_mapping`` rig's fixed schema has no
    such column, so this test builds its own."""
    db = session_factory()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, doc_date TEXT, last_modified TEXT, line_count INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT)"
        )
        for row in [
            # D001: fingerprint says 3 lines exist; the line query finds 0 -
            # a genuine mismatch (a broken line query/join, not a real
            # zero-line document).
            ("D001", "SO-001", "open", "2026-08-01", "2026-08-01 09:00:00", 3),
            # D002: fingerprint says 0 lines, and 0 really exist - a
            # perfectly valid lineless document (AC-13's own "a document
            # with no lines is a valid record" rule).
            ("D002", "SO-002", "open", "2026-08-02", "2026-08-02 09:00:00", 0),
        ]:
            conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?, ?)", row)
        # No so_line rows for EITHER header - D001's fingerprint disagrees,
        # D002's does not.

    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp",
        name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_R4B",
        company_name="R4B Co", name="R4B", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    conn_row = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="Source DB",
        config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                     "database": "AED_R4B", "username": "readonly"},
        credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
    )
    db.add(conn_row)
    db.commit()
    db.refresh(conn_row)
    RUNTIME.put_engine(conn_row.id, engine)

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": conn_row.id,
        "query": (
            "SELECT doc_key, doc_no, status, doc_date, last_modified, "
            "line_count AS LineCount FROM so_header"
        ),
        "lineQuery": "SELECT dtl_key, item_code, qty_ordered FROM so_line WHERE doc_key = :doc_key",
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
    config.result_columns = ["doc_key", "doc_no", "status", "doc_date", "last_modified", "LineCount"]
    db.add(config)
    db.commit()
    db.refresh(config)

    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="doc_no",
        canonical_field="so_number", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_HEADER, source_path="status",
        canonical_field="status", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="dtl_key",
        canonical_field="source_ref", transform="string", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="item_code",
        canonical_field="product_ref", transform="ref_product", required=True,
    )
    _seed_row(
        db, company, scope=SCOPE_LINE, source_path="qty_ordered",
        canonical_field="qty_ordered", transform="decimal", required=True,
    )
    db.commit()
    return db, company, engine


def test_a_line_count_mismatch_fails_the_header_a_genuine_zero_lines_does_not(
    session_factory,
):
    db, company, engine = _line_count_rig(session_factory)
    try:
        job = JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={
                "companyId": company.id, "entityType": ENTITY_SALES_ORDER,
                "mode": "manual",
            },
        )
        run = db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()

        staged = {
            r.source_ref: r
            for r in db.query(AcStagedRecord).filter(
                AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
                AcStagedRecord.company_id == company.id,
                AcStagedRecord.entity_type == ENTITY_SALES_ORDER,
            )
        }
        d001 = next((r for ref, r in staged.items() if ref.endswith(":D001")), None)
        d002 = next((r for ref, r in staged.items() if ref.endswith(":D002")), None)
        assert d001 is not None and d002 is not None, (
            f"expected both D001 and D002 staged - got refs {sorted(staged)}"
        )

        assert d001.status == STAGED_FAILED, (
            f"D001 (LineCount=3, 0 lines fetched) must be staged FAILED - "
            f"got {d001.status!r}"
        )
        assert "3" in (d001.error or "") and "0" in (d001.error or ""), (
            f"D001's error must name the mismatch (LineCount vs lines "
            f"fetched) - got {d001.error!r}"
        )
        assert d001.canonical_json is None, "a failed document stores no canonical payload (D13)"

        assert d002.status == STAGED, (
            f"D002 (LineCount=0, 0 lines fetched) is a genuinely valid "
            f"lineless document - got {d002.status!r} ({d002.error!r})"
        )

        assert run.failed_count == 1, f"expected failed_count=1, got {run.failed_count}"
    finally:
        RUNTIME.dispose_all()
    db.close()
