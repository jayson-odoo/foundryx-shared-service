"""SO/PO documents (plan 22 S5, AC-22-24) - the last DB-ETL build slice.

Nothing here forks a new code path: canonical shape -> flat mapping (with the
new per-header line fetch + ref minting) -> Sorento sink routing, exactly the
seams S1-S4 already proved for masters. What is genuinely NEW in this slice
and therefore pinned here:

* the two canonical document shapes (golden payloads, status vocabulary, line
  duplicate-ref guard);
* master-ref minting (``ref_customer``/``ref_product``/…/``ref_sales_agent``)
  and the header/line ref schemes (``{db}:{DocKey}`` /
  ``{db}:{DocKey}:{DtlKey}``);
* the FIXED column-name line-mapping generator (``mapping.document_line_rows``);
* ``SqlDbSource``'s document mode - watermark REQUIRED, the fromDate floor,
  one guarded/bound lineQuery per changed header, no delete-guard/intents;
* the save-time validation for the new source_config fields + the lineQuery
  preview leg;
* sink routing + the "unknown ref -> retryable" carry-over;
* read-back tolerating a line we never sent (Appendix A7).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List

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
    MappingEngine,
    MappingRow,
    SCOPE_HEADER,
    SCOPE_LINE,
    document_line_rows,
    flat_profile,
    flat_source_ref,
    mint_master_ref,
)
from modules.autocount.models import (
    AcCompany,
    AcEntityConfig,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService
from modules.autocount.services.sync_service import CANONICAL_MODELS
from modules.autocount.sinks_sorento import (
    SorentoSink,
    sorento_supported_entities_label,
    sorento_supports_entity,
)
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.errors import SqlDocumentCapExceeded
from modules.autocount.sql_source.source import SqlDbSource, SqlTaskNotConfigured
from modules.autocount.sql_source import source as sql_db_source_module

DB = "AED_VSOFT"


# ── canonical golden payloads (Appendix A6 §3) ───────────────────────────────


def test_sales_order_sink_payload_is_exactly_the_A6_shape():
    rec = CanonicalSalesOrder(
        source_ref=f"{DB}:D1", so_number="SO-001", customer_ref=f"{DB}:C1",
        sales_agent_ref="agent:SA01", doc_date="2026-01-05",
        requested_delivery_date="2026-01-20", status="open",
        internal_note="rush order",
        lines=[
            CanonicalSalesOrderLine(
                source_ref=f"{DB}:D1:L1", product_ref=f"{DB}:P1", warehouse_ref=f"{DB}:W1",
                qty_ordered=Decimal("10"), qty_delivered=Decimal("2"),
                unit_price=Decimal("9.99"), discount=Decimal("0.50"),
                line_total=Decimal("94.40"), uom="PCS", required_date="2026-01-15",
            )
        ],
    )
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:D1", "so_number": "SO-001", "customer_ref": f"{DB}:C1",
        "sales_agent_ref": "agent:SA01", "doc_date": "2026-01-05",
        "requested_delivery_date": "2026-01-20", "status": "open",
        "internal_note": "rush order",
        "lines": [
            {
                "source_ref": f"{DB}:D1:L1", "product_ref": f"{DB}:P1",
                "warehouse_ref": f"{DB}:W1", "qty_ordered": "10",
                "qty_delivered": "2", "unit_price": "9.99", "discount": "0.50",
                "line_total": "94.40", "uom": "PCS", "required_date": "2026-01-15",
            }
        ],
    }


def test_purchase_order_sink_payload_is_exactly_the_A6_shape():
    rec = CanonicalPurchaseOrder(
        source_ref=f"{DB}:D2", po_number="PO-001", supplier_ref=f"{DB}:S1",
        issue_date="2026-02-01", expected_date="2026-02-10", currency="MYR",
        status="partial",
        lines=[
            CanonicalPurchaseOrderLine(
                source_ref=f"{DB}:D2:L1", product_ref=f"{DB}:P2",
                qty_ordered=Decimal("5"), qty_received=Decimal("5"),
                unit_cost=Decimal("3.20"), uom="EA",
            )
        ],
    )
    # NO `internal_note` here - Sorento's PO schema has no such field (unlike
    # SO's own); sending it trips their extra="forbid" (live-verify catch).
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:D2", "po_number": "PO-001", "supplier_ref": f"{DB}:S1",
        "issue_date": "2026-02-01", "expected_date": "2026-02-10", "currency": "MYR",
        "status": "partial",
        "lines": [
            {
                "source_ref": f"{DB}:D2:L1", "product_ref": f"{DB}:P2",
                "warehouse_ref": None, "qty_ordered": "5", "qty_received": "5",
                "unit_cost": "3.20", "discount": None, "line_total": None,
                "uom": "EA", "currency": None, "expected_date": None,
            }
        ],
    }


def test_purchase_order_never_sends_internal_note_even_when_set():
    """Live-verify regression pin: Sorento's PO schema has no `internal_note`
    field (only SO's does) - sending it 422s every push with "Extra inputs
    are not permitted", quarantining every purchase order."""
    rec = CanonicalPurchaseOrder(
        source_ref="x", po_number="PO-1", status="open", internal_note="set on purpose",
    )
    assert "internal_note" not in rec.sink_payload()


def test_status_must_be_in_the_fixed_five_word_vocabulary():
    assert set(DOCUMENT_STATUS_VALUES) == {
        "open", "partial", "fulfilled", "closed", "cancelled",
    }
    with pytest.raises(Exception):
        CanonicalSalesOrder(source_ref="x", status="shipped")


def test_a_document_with_no_lines_is_a_perfectly_valid_record():
    rec = CanonicalPurchaseOrder(source_ref="x", po_number="PO-1", status="closed")
    assert rec.sink_payload()["lines"] == []


def test_duplicate_line_refs_are_rejected_at_construction():
    with pytest.raises(Exception):
        CanonicalSalesOrder(
            source_ref="x", status="open",
            lines=[
                CanonicalSalesOrderLine(source_ref="L1", product_ref="P1", qty_ordered=Decimal("1")),
                CanonicalSalesOrderLine(source_ref="L1", product_ref="P2", qty_ordered=Decimal("1")),
            ],
        )


# ── an unknown status surfaces as mapped.errors AT MAPPING TIME (Appendix A6
# item 2 - never a silent push-time surprise) ─────────────────────────────────


def test_an_unrecognised_status_surfaces_in_mapped_errors_not_a_push_time_surprise():
    engine = MappingEngine(
        [
            MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
            MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
            MappingRow("Status", "status", "string", SCOPE_HEADER),
        ],
        entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]),
        database_name=DB,
    )
    mapped = engine.map_document({"DocKey": "D1", "DocNo": "SO-1", "Status": "shipped"})
    assert not mapped.ok
    assert mapped.record is None
    assert any("status" in e.message().lower() or "document" in e.field for e in mapped.errors)


# ── master-ref minting (Appendix A6 item 3) - reuses flat_source_ref, so it
# can never drift from the master task's OWN identity scheme ────────────────


def test_mint_master_ref_matches_the_master_tasks_own_scheme():
    assert mint_master_ref("C1", database_name=DB, entity_type="customer") == f"{DB}:C1"
    assert mint_master_ref("W1", database_name=DB, entity_type="warehouse") == f"{DB}:W1"
    # sales_agent is the ONE unqualified scheme (upper/trim, `agent:{CODE}`).
    assert mint_master_ref(" sa01 ", database_name=DB, entity_type="sales_agent") == "agent:SA01"


def test_mint_master_ref_blank_passes_through_as_none():
    assert mint_master_ref("", database_name=DB, entity_type="customer") is None
    assert mint_master_ref(None, database_name=DB, entity_type="customer") is None


def test_header_ref_transforms_map_through_the_real_engine():
    engine = MappingEngine(
        [
            MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
            MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
            MappingRow("Status", "status", "string", SCOPE_HEADER),
            MappingRow("CustomerCode", "customer_ref", "ref_customer", SCOPE_HEADER),
            MappingRow("AgentCode", "sales_agent_ref", "ref_sales_agent", SCOPE_HEADER),
        ],
        entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]),
        database_name=DB,
    )
    mapped = engine.map_document(
        {"DocKey": "D1", "DocNo": "SO-1", "Status": "open", "CustomerCode": "C1", "AgentCode": "sa01"}
    )
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.customer_ref == f"{DB}:C1"
    assert mapped.record.sales_agent_ref == "agent:SA01"


def test_header_and_line_refs_follow_the_two_tier_A6_scheme_end_to_end():
    """header = ``{db}:{DocKey}``, line = ``{db}:{DocKey}:{DtlKey}`` - and a
    line's ``product_ref``/``warehouse_ref`` mint the SAME scheme a master
    task mints for its own identity."""
    header_rows = [
        MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
        MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
        MappingRow("Status", "status", "string", SCOPE_HEADER),
    ]
    config = {"lineKeyColumn": "DtlKey", "lineProductColumn": "ItemCode", "lineWarehouseColumn": "Location"}
    rows = header_rows + document_line_rows(ENTITY_SALES_ORDER, config)
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name=DB,
    )
    mapped = engine.map_document({
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open",
        "_lines": [
            {"DtlKey": "L1", "ItemCode": "P1", "Location": "W1", "qty_ordered": "10"},
        ],
    })
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == f"{DB}:D1"
    [line] = mapped.record.lines
    assert line.source_ref == f"{DB}:D1:L1"
    assert line.product_ref == f"{DB}:P1"
    assert line.warehouse_ref == f"{DB}:W1"
    assert line.qty_ordered == Decimal("10")


# ── document_line_rows: the FIXED column-name convention generator ──────────


def test_document_line_rows_is_empty_without_a_line_key_column():
    assert document_line_rows(ENTITY_SALES_ORDER, {}) == []
    assert document_line_rows(ENTITY_SALES_ORDER, {"lineProductColumn": "ItemCode"}) == []


def test_document_line_rows_marks_source_ref_and_product_ref_required():
    rows = document_line_rows(
        ENTITY_SALES_ORDER,
        {"lineKeyColumn": "DtlKey", "lineProductColumn": "ItemCode"},
    )
    by_field = {r.canonical_field: r for r in rows}
    assert by_field["source_ref"].is_required is True
    assert by_field["product_ref"].is_required is True
    assert "warehouse_ref" not in by_field  # no column configured -> no row
    assert by_field["qty_ordered"].is_required is True  # Sorento's own required field
    assert by_field["uom"].is_required is False


def test_document_line_rows_fixed_names_differ_between_so_and_po():
    so_fields = {r.canonical_field for r in document_line_rows(
        ENTITY_SALES_ORDER, {"lineKeyColumn": "DtlKey", "lineProductColumn": "ItemCode"}
    )}
    po_fields = {r.canonical_field for r in document_line_rows(
        ENTITY_PURCHASE_ORDER, {"lineKeyColumn": "DtlKey", "lineProductColumn": "ItemCode"}
    )}
    assert "qty_delivered" in so_fields and "qty_delivered" not in po_fields
    assert "qty_received" in po_fields and "qty_received" not in so_fields
    assert "currency" in po_fields and "currency" not in so_fields


# ── flat_profile carries line_model/detail_key/line_ref_prefix for docs ─────


def test_flat_profile_registers_the_document_canonical_models_with_lines():
    so = flat_profile(ENTITY_SALES_ORDER, ["DocKey"])
    assert so.record_model is CanonicalSalesOrder
    assert so.line_model is CanonicalSalesOrderLine
    assert so.line_ref_prefix is True
    po = flat_profile(ENTITY_PURCHASE_ORDER, ["DocKey"])
    assert po.record_model is CanonicalPurchaseOrder
    assert po.line_model is CanonicalPurchaseOrderLine


def test_flat_profile_still_gives_masters_no_lines_at_all():
    """S1 regression pin - S5's line_model/detail_key carry-through must not
    accidentally hand a master (or GRN) lines it never had."""
    from modules.autocount.canonical.masters import ENTITY_CUSTOMER

    profile = flat_profile(ENTITY_CUSTOMER, ["AccNo"])
    assert profile.line_model is None
    assert profile.detail_key is None
    assert profile.line_ref_prefix is False


# ── sinks_sorento: routing + retryable-on-unknown-ref carry-over ────────────


@pytest.mark.parametrize(
    "entity_type,segment",
    [(ENTITY_SALES_ORDER, "sales_orders"), (ENTITY_PURCHASE_ORDER, "purchase_orders")],
)
def test_entity_path_maps_to_the_plural_document_route(entity_type, segment):
    requests: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        records = [
            {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "id-1"}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": len(records), "created": len(records), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": records,
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=entity_type,
                        transport=httpx.MockTransport(handle))
    record = (
        CanonicalSalesOrder(source_ref="ref-1", so_number="SO-1", status="open")
        if entity_type == ENTITY_SALES_ORDER
        else CanonicalPurchaseOrder(source_ref="ref-1", po_number="PO-1", status="open")
    )
    sink.write_batch([record], request_id="t")
    assert requests[0].url.path == f"/api/v1/external/ingest/{segment}"


def test_sorento_supports_both_documents():
    assert sorento_supports_entity(ENTITY_SALES_ORDER)
    assert sorento_supports_entity(ENTITY_PURCHASE_ORDER)


def test_sorento_supported_entities_label_is_derived_from_the_entity_path_map():
    """S6 merge-gate review NIT 7 - the preview 'not previewable' reason used
    to hardcode 'suppliers and customers only', which went stale the moment
    documents joined ``_ENTITY_PATH`` (plan 22 S5). The label is generated
    FROM the map so it can never drift again - every current entry (masters
    AND documents) appears, in the map's own order, joined with a trailing
    'and' (no serial comma), and GRN (absent from the map) does not."""
    label = sorento_supported_entities_label()
    for entity_type in (
        "supplier",
        "customer",
        "product category",
        "unit of measure",
        "warehouse",
        "product",
        "sales agent",
        "sales order",
        "purchase order",
    ):
        assert entity_type in label
    assert label.endswith("sales agent, sales order and purchase order")
    assert "goods received note" not in label
    assert "grn" not in label.lower()


def test_an_unknown_master_ref_is_retryable_not_a_defect_signal():
    """Appendix A6 item 3 - "unknown ref = whole record retryable". A
    document is now a DEPENDENT entity (mirrors the product/category-UOM
    carry-over already proved for masters, AC-22-23)."""
    def handle(request: httpx.Request) -> httpx.Response:
        ref = json.loads(request.content)["records"][0]["source_ref"]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 0, "failed": 0, "retryable": 1},
            "records": [{"source_ref": ref, "outcome": "retryable", "entity_id": None}],
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_SALES_ORDER,
                        transport=httpx.MockTransport(handle))
    [result] = sink.write_batch(
        [CanonicalSalesOrder(source_ref="ref-1", so_number="SO-1", status="open",
                              customer_ref="unknown:ref")],
        request_id="t",
    )
    assert result.delivered is False
    assert result.outcome == "retryable"
    assert "unreachable" not in result.message.lower()


def test_sync_service_rehydrates_documents_from_canonical_json():
    assert CANONICAL_MODELS[ENTITY_SALES_ORDER] is CanonicalSalesOrder
    assert CANONICAL_MODELS[ENTITY_PURCHASE_ORDER] is CanonicalPurchaseOrder
    record = CanonicalSalesOrder(
        source_ref="x", so_number="SO-1", status="open",
        lines=[CanonicalSalesOrderLine(source_ref="x:L1", product_ref="p", qty_ordered=Decimal("1"))],
    )
    rehydrated = CanonicalSalesOrder(**record.comparable())
    assert rehydrated.lines[0].qty_ordered == Decimal("1")


# ── read-back tolerates a line we never sent (Appendix A7 item 1) ───────────


def test_read_back_tolerates_a_cancelled_line_we_never_sent():
    """A re-push can come back carrying a line with a cancelled ``line_status``
    that this ESB never sent (a Sorento-side dependent kept it instead of
    deleting it). ``read_back`` must not choke on it or drop it - callers
    (a future diff/drift render) must not treat it as unexpected drift."""
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "records": [{
                "source_ref": "x", "entity_id": "so-1", "so_number": "SO-1",
                "status": "open", "customer_ref": None,
                "lines": [
                    {"source_ref": "x:L1", "entity_id": "l-1", "product_ref": "p1",
                     "qty_ordered": 10, "qty_delivered": 2},
                    # A line we never sent - kept cancelled rather than deleted
                    # (A7 item 1). Extra keys pass through untouched.
                    {"source_ref": "x:L2", "entity_id": "l-2", "product_ref": "p2",
                     "qty_ordered": 5, "line_status": "cancelled"},
                ],
            }],
            "not_found": [],
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_SALES_ORDER,
                        transport=httpx.MockTransport(handle))
    result = sink.read_back(["x"])
    assert result["not_found"] == []
    [record] = result["records"]
    lines = record["lines"]
    assert len(lines) == 2
    cancelled = next(l for l in lines if l["source_ref"] == "x:L2")
    assert cancelled["line_status"] == "cancelled"
    # Numbers came back as JSON numbers - decimalised via str(), never a float.
    assert record["lines"][0]["qty_ordered"] == Decimal("10")
    assert isinstance(record["lines"][0]["qty_ordered"], Decimal)


# ── validate_source_config: the S5 fields (AC-22-11 extended) ───────────────


def _base_so_config(**overrides) -> Dict[str, Any]:
    base = {
        "connectionId": "c1",
        "query": "SELECT DocKey, DocNo, Status, DocDate FROM SOHeader",
        "lineQuery": "SELECT DtlKey, ItemCode FROM SODetail WHERE DocKey = :doc_key",
        "keyColumns": ["DocKey"],
        "watermarkColumn": "DocDate",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "DocDate",
        "lineKeyColumn": "DtlKey",
        "lineProductColumn": "ItemCode",
        "lineWarehouseColumn": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    base.update(overrides)
    return base


_HEADER_COLUMNS = {"DocKey": "string", "DocNo": "string", "Status": "string", "DocDate": "datetime"}
_LINE_COLUMNS = {"DtlKey": "string", "ItemCode": "string"}


def test_a_document_task_requires_a_watermark_column():
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER, _base_so_config(watermarkColumn=None), _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert "watermarkColumn" in errors
    assert "LastModified" in errors["watermarkColumn"] or "line" in errors["watermarkColumn"].lower()


def test_a_document_task_requires_the_line_ref_and_date_columns():
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER,
        _base_so_config(docDateColumn=None, lineKeyColumn=None, lineProductColumn=None),
        _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert "docDateColumn" in errors
    assert "lineKeyColumn" in errors
    assert "lineProductColumn" in errors


def test_a_document_task_line_columns_are_checked_against_the_line_preview():
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER,
        _base_so_config(lineProductColumn="NotAColumn"),
        _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert "lineProductColumn" in errors


def test_a_document_task_requires_the_line_query_to_bind_doc_key():
    """S5 review BLOCKER 1: a lineQuery with no ``:doc_key`` bind previews and
    would otherwise save clean (SQLAlchemy silently ignores an unused param),
    then attach the WHOLE line table to every header at run time."""
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER,
        _base_so_config(lineQuery="SELECT DtlKey, ItemCode FROM SODetail"),
        _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert "lineQuery" in errors
    assert "doc_key" in errors["lineQuery"]


def test_a_document_task_line_query_bind_check_ignores_a_mention_in_a_comment():
    """A comment or literal merely MENTIONING ``:doc_key`` must not count -
    the check runs the real compiler, never a substring search."""
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER,
        _base_so_config(
            lineQuery="SELECT DtlKey, ItemCode FROM SODetail -- filter by :doc_key later"
        ),
        _HEADER_COLUMNS,
        line_columns=_LINE_COLUMNS,
    )
    assert "lineQuery" in errors
    assert "doc_key" in errors["lineQuery"]


def test_a_valid_document_config_saves_clean():
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER, _base_so_config(), _HEADER_COLUMNS, line_columns=_LINE_COLUMNS,
    )
    assert errors == {}
    assert clean["docDateColumn"] == "DocDate"
    assert clean["lineKeyColumn"] == "DtlKey"
    assert clean["lineProductColumn"] == "ItemCode"


def test_a_non_document_entity_never_carries_the_new_fields():
    from modules.autocount.services.etl_service import validate_source_config

    clean, errors = validate_source_config(
        "customer",
        {"connectionId": "c1", "query": "SELECT AccNo FROM Debtor", "keyColumns": ["AccNo"]},
        {"AccNo": "string"},
    )
    assert clean["docDateColumn"] is None
    assert clean["lineKeyColumn"] is None


# ── SqlDbSource - document extraction end to end (SQLite rig) ───────────────

SO_ROWS = [
    ("D001", "SO-001", "open", "2026-08-01", "2026-08-01 09:00:00"),
    ("D002", "SO-002", "open", "2026-08-02", "2026-08-02 09:00:00"),
]
SO_LINES = {
    "D001": [("D001-1", "ITEM-A", "10")],
    "D002": [("D002-1", "ITEM-B", "5"), ("D002-2", "ITEM-C", "3")],
}


def _source_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, doc_date TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT)"
        )
        for row in SO_ROWS:
            conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?)", row)
        for doc_key, lines in SO_LINES.items():
            for dtl_key, item_code, qty in lines:
                conn.exec_driver_sql(
                    "INSERT INTO so_line VALUES (?, ?, ?, ?)", (dtl_key, doc_key, item_code, qty)
                )
    return engine


def _sql_connection(db, engine) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp",
        name="Source DB",
        config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                     "database": DB, "username": "readonly"},
        credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    RUNTIME.put_engine(conn.id, engine)
    return conn


def _company(db) -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=DB,
        company_name="AED Sdn Bhd", name="AED", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


HEADER_QUERY = "SELECT doc_key, doc_no, status, doc_date, last_modified FROM so_header"
LINE_QUERY = "SELECT dtl_key, item_code, qty_ordered FROM so_line WHERE doc_key = :doc_key"


def _configure(db, company, connection_id: str, **overrides) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
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
    config.result_columns = ["doc_key", "doc_no", "status", "doc_date", "last_modified"]
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    engine = _source_engine()
    conn = _sql_connection(db, engine)
    company = _company(db)
    config = _configure(db, company, conn.id)
    yield db, company, config, engine
    db.close()
    RUNTIME.dispose_all()


def test_the_initial_load_fetches_every_header_and_its_own_lines(rig):
    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    result = source.fetch_changes(Watermark())

    assert len(result.records) == 2
    by_doc_key = {r.raw["doc_key"]: r.raw for r in result.records}
    assert by_doc_key["D001"]["_lines"] == [
        {"dtl_key": "D001-1", "item_code": "ITEM-A", "qty_ordered": "10"}
    ]
    assert len(by_doc_key["D002"]["_lines"]) == 2


def test_a_construction_time_backstop_requires_a_watermark_column(rig):
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "watermarkColumn": None}
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)


def test_a_construction_time_backstop_requires_a_line_query(rig):
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "lineQuery": ""}
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)


def test_a_construction_time_backstop_requires_the_line_query_to_bind_doc_key(rig):
    """S5 review BLOCKER 1 - a row edited straight into the JSON column with
    a lineQuery that never filters on ``:doc_key`` must not sail through at
    run time (SQLAlchemy silently ignores an unused param)."""
    db, company, config, _engine = rig
    config.source_config = {
        **config.source_config,
        "lineQuery": "SELECT dtl_key, item_code, qty_ordered FROM so_line",
    }
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)


def test_a_composite_header_key_is_refused_for_documents(rig):
    """A document's header key doubles as the lineQuery's :doc_key bind - a
    composite key would be ambiguous about which part to bind (S5 design
    decision)."""
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "keyColumns": ["doc_key", "doc_no"]}
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)


def test_the_from_date_floor_excludes_a_header_older_than_it(rig):
    db, company, config, engine = rig
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO so_header VALUES ('D000', 'SO-000', 'open', '2025-01-01', "
            "'2025-01-01 09:00:00')"
        )
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    result = source.fetch_changes(Watermark())
    assert {r.raw["doc_key"] for r in result.records} == {"D001", "D002"}


def test_the_from_date_floor_still_applies_on_an_incremental_read(rig):
    db, company, config, engine = rig
    cursor = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER
    ).fetch_changes(Watermark()).cursor
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO so_header VALUES ('D999', 'SO-999', 'open', '2025-01-01', "
            "'2026-08-05 09:00:00')"
        )  # newer LastModified, but a doc_date BEFORE the from-date floor
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER
    ).fetch_changes(Watermark(cursor=cursor))
    assert result.records == []


def test_only_a_changed_header_re_fetches_its_lines(rig):
    """AutoCount stamps a header's LastModified on any line edit - the S5
    line-change-detection decision (a line-only edit still shows up here
    because touching the header row IS what makes it 'changed')."""
    db, company, config, engine = rig
    cursor = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER
    ).fetch_changes(Watermark()).cursor
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO so_line VALUES ('D001-2', 'D001', 'ITEM-X', '1')"
        )
        conn.exec_driver_sql(
            "UPDATE so_header SET last_modified = '2026-08-10 09:00:00' WHERE doc_key = 'D001'"
        )
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER
    ).fetch_changes(Watermark(cursor=cursor))
    assert [r.raw["doc_key"] for r in result.records] == ["D001"]
    assert len(result.records[0].raw["_lines"]) == 2  # the new line is picked up


# ── document N+1 caps (S5 review SHOULD-FIX 3) ───────────────────────────────


def test_too_many_changed_headers_trips_the_named_document_cap(rig, monkeypatch):
    """A run fanning out to more changed headers than the safety cap fails
    the WHOLE run (nothing staged/pushed), naming the DOCUMENT_CAP guard -
    never a silent unbounded round-trip storm."""
    db, company, config, _engine = rig
    monkeypatch.setattr(sql_db_source_module, "MAX_DOCUMENT_HEADERS_PER_RUN", 1)
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    with pytest.raises(SqlDocumentCapExceeded) as exc:
        source.fetch_changes(Watermark())
    assert "2" in str(exc.value)  # the rig has 2 headers, over the cap of 1


def test_under_the_header_cap_runs_normally(rig, monkeypatch):
    db, company, config, _engine = rig
    monkeypatch.setattr(sql_db_source_module, "MAX_DOCUMENT_HEADERS_PER_RUN", 100)
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 2


def test_a_header_with_too_many_line_rows_trips_the_named_document_cap(rig, monkeypatch):
    """A ``lineQuery`` matching far more than its own header's rows (a loose
    WHERE clause, or none at all) must not silently attach thousands of
    unrelated rows to one document."""
    db, company, config, _engine = rig
    monkeypatch.setattr(sql_db_source_module, "MAX_DOCUMENT_LINES_PER_HEADER", 1)
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    with pytest.raises(SqlDocumentCapExceeded) as exc:
        source.fetch_changes(Watermark())
    assert "D002" in str(exc.value)  # D002 has 2 lines, over the cap of 1


def test_under_the_line_cap_runs_normally(rig, monkeypatch):
    db, company, config, _engine = rig
    monkeypatch.setattr(sql_db_source_module, "MAX_DOCUMENT_LINES_PER_HEADER", 100)
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    result = source.fetch_changes(Watermark())
    by_doc_key = {r.raw["doc_key"]: r.raw for r in result.records}
    assert len(by_doc_key["D002"]["_lines"]) == 2


def test_a_document_cap_trip_surfaces_as_a_named_error_code_through_sync(rig, monkeypatch):
    """End to end through the real job handler (mirrors the DELETE_GUARD
    sync-level test in test_autocount_reconcile_push.py): the run FAILS with
    a distinct, unprefixed ``DOCUMENT_CAP`` error code - never a generic
    ``Fetch failed:``."""
    from app.models.background_job import JOB_FAILED

    from modules.autocount.services.sync_service import SyncService

    db, company, config, _engine = rig
    monkeypatch.setattr(sql_db_source_module, "MAX_DOCUMENT_HEADERS_PER_RUN", 1)
    job = SyncService(db).sync_now(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, actor_user_id=None
    )
    db.refresh(job)
    assert job.status == JOB_FAILED
    assert not (job.error or "").startswith("Fetch failed:")
    db.refresh(config)
    assert config.last_run_error_code == "DOCUMENT_CAP"


def test_reconcile_reports_no_delete_refs_even_when_a_header_is_missing(rig):
    db, company, config, engine = rig
    SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER).fetch_changes(
        Watermark()
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM so_header WHERE doc_key = 'D002'")
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER, mode=RUN_MODE_RECONCILE
    ).fetch_changes(Watermark())
    # A shrink that WOULD trip the guard for a master (1 of 2 known = 50%,
    # over the ratio floor) is a complete non-event for a document.
    assert result.delete_refs == []


def test_a_document_writes_one_hash_per_header_keyed_on_the_header_ref(rig):
    db, company, config, _engine = rig
    SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER).fetch_changes(
        Watermark()
    )
    stored = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    assert set(stored) == {f"{DB}:D001", f"{DB}:D002"}
    assert all(len(h) == 64 for h in stored.values())


def test_a_second_run_with_only_a_line_change_reports_it_as_an_update(rig):
    db, company, config, engine = rig
    SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER).fetch_changes(
        Watermark()
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE so_line SET qty_ordered = '99' WHERE dtl_key = 'D001-1'"
        )
        conn.exec_driver_sql(
            "UPDATE so_header SET last_modified = '2026-08-15 09:00:00' WHERE doc_key = 'D001'"
        )
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_SALES_ORDER, mode=RUN_MODE_RECONCILE
    ).fetch_changes(Watermark())
    assert "D001" in {r.raw["doc_key"] for r in result.records}


# ── end-to-end: extract -> map -> stage, lines land with prefixed refs ──────


def test_the_full_pipeline_maps_a_header_and_its_lines_with_prefixed_refs(rig):
    from modules.autocount.mapping import MappingEngine, document_line_rows

    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_SALES_ORDER)
    result = source.fetch_changes(Watermark())
    source.close()

    header_rows = [
        MappingRow("doc_key", "source_ref", "string", SCOPE_HEADER),
        MappingRow("doc_no", "so_number", "string", SCOPE_HEADER),
        MappingRow("status", "status", "string", SCOPE_HEADER),
    ]
    rows = header_rows + document_line_rows(ENTITY_SALES_ORDER, config.source_config)
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, config.source_config["keyColumns"]),
        database_name=company.database_name,
    )
    mapped = [engine.map_document(r.raw) for r in result.records]
    assert all(m.ok for m in mapped), [e.message() for m in mapped for e in m.errors]

    by_ref = {m.record.source_ref: m.record for m in mapped}
    d001 = by_ref[f"{DB}:D001"]
    assert d001.so_number == "SO-001"
    assert d001.status == "open"
    [line] = d001.lines
    assert line.source_ref == f"{DB}:D001:D001-1"
    assert line.product_ref == f"{DB}:ITEM-A"
    assert line.qty_ordered == Decimal("10")


# ── sync._stage_deletes: documents suppress delete intents entirely ─────────


def test_stage_deletes_suppresses_document_delete_intents(session_factory):
    from app.models.background_job import JOB_DONE, BackgroundJob
    from modules.autocount.repositories import StagedRecordRepository
    from modules.autocount.sync import _stage_deletes

    db = session_factory()
    company = _company(db)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, {f"{DB}:GONE": "h"},
        seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db.commit()
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type="autocount_sync", status=JOB_DONE)
    db.add(job)
    db.commit()
    db.refresh(job)

    staged = _stage_deletes(
        db, job, [f"{DB}:GONE"], tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_SALES_ORDER, current_refs=[],
    )
    assert staged == 0
    assert StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id) == []
    # The local hash row for the missing ref IS dropped (so a re-appearance
    # stages as a fresh add, never a phantom update) - same treatment as a
    # shared entity.
    assert RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER) == {}
    db.close()


# ── the preview lineQuery leg (EtlService.preview with a bound sample) ──────


def test_previewing_the_line_query_binds_a_harmless_doc_key(session_factory):
    db = session_factory()
    engine = _source_engine()
    conn = _sql_connection(db, engine)
    result = EtlService(db).preview(DEFAULT_TENANT_ID, conn.id, LINE_QUERY, bind_doc_key=True, doc_key=None)
    assert {c.name for c in result.columns} == {"dtl_key", "item_code", "qty_ordered"}
    assert result.row_count == 0  # WHERE doc_key = NULL matches nothing - by design
    db.close()
    RUNTIME.dispose_all()


def test_previewing_the_line_query_with_a_real_sample_returns_its_rows(session_factory):
    db = session_factory()
    engine = _source_engine()
    conn = _sql_connection(db, engine)
    result = EtlService(db).preview(DEFAULT_TENANT_ID, conn.id, LINE_QUERY, bind_doc_key=True, doc_key="D002")
    assert result.row_count == 2
    db.close()
    RUNTIME.dispose_all()
