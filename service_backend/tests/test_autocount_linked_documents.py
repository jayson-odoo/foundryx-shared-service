"""AC-CANCEL-PULL - Cancel SO / Cancel PO / Consignment / Consignment Return.

Four more AutoCount documents pulled through the existing DATABASE source
(``source_impl = sql_db``) exactly like SO/PO/SPO, and pushed to the CRM
behind contract 2.8. What is NEW and therefore pinned here:

* the WIRE is the DO/GRN doc-feed shape the CRM (#1623) already ingests:
  body ``{companyCode, book, records}``, each record the AutoCount header row
  under its own PascalCase column names with its lines in ``Details``,
  ``source_ref`` = the CRM's own ``{book}:{XS|XP|CG|CR}:{DocKey}``, and
  deletions by ``doc_keys``;
* the link columns ``FromDocType``/``FromDocNo``/``FromDocDtlKey`` ride every
  line with ``ItemCode``/``Location``/``Qty`` (``FromDocDtlKey`` is often empty,
  so the CRM matches on the other four);
* the four ``DocumentPreset`` rows (SQL text shape, ``:doc_key`` bind, every
  preset row targets a catalog field) mapped end to end through the REAL
  engine with fake rows;
* the contract-2.8 sink gate, and ``auto_push``'s refusal to "deliver"
  through the logging-sink fallback (that would mark rows PUSHED while
  nothing landed - a silent, permanent loss).

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    DOCUMENT_ENTITY_TYPES,
    ENTITY_CANCEL_PURCHASE_ORDER,
    ENTITY_CANCEL_SALES_ORDER,
    ENTITY_CONSIGNMENT,
    ENTITY_CONSIGNMENT_RETURN,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    LINE_QUERY_DOC_KEY_PARAM,
    LINKED_DOCUMENT_ENTITY_TYPES,
    CanonicalCancelPurchaseOrder,
    CanonicalCancelSalesOrder,
    CanonicalConsignment,
    CanonicalConsignmentReturn,
    CanonicalLinkedDocumentLine,
    is_document_entity,
    linked_document_ref,
)
from modules.autocount.mapping import (
    ENTITY_PROFILES,
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    flat_profile,
)
from modules.autocount.mapping_catalog import (
    accepted_field_names,
    line_accepted_field_names,
    line_required_field_names,
    required_field_names,
)
from modules.autocount.models import STAGED, AcStagedRecord
from modules.autocount.presets import DOCUMENT_PRESETS
from modules.autocount.services.etl_service import ETL_ENTITY_TYPES
from modules.autocount.services.sync_service import CANONICAL_MODELS
from modules.autocount.sinks import SINK_LOGGING
from modules.autocount.sinks_sorento import (
    CONTRACT_GATED_ENTITIES,
    LINKED_DOCUMENTS_CONTRACT_VERSION,
    SorentoContractInfo,
    SorentoSink,
    sorento_supported_entities_label,
    sorento_supports_entity,
)
from modules.autocount.sync import AUTOCOUNT_SYNC

# Re-used verbatim: a real Sorento-sink AcCompany rig (pytest picks the
# fixture up by name once it is imported into this module).
from tests.test_s13_stock_push_contract_gate import _stock_gate_rig  # noqa: F401

DB = "FAKE_BOOK"

SEGMENTS: Dict[str, str] = {
    ENTITY_CANCEL_SALES_ORDER: "cancel_sales_orders",
    ENTITY_CANCEL_PURCHASE_ORDER: "cancel_purchase_orders",
    ENTITY_CONSIGNMENT: "consignments",
    ENTITY_CONSIGNMENT_RETURN: "consignment_returns",
}

TABLES: Dict[str, tuple] = {
    ENTITY_CANCEL_SALES_ORDER: ("XS", "XSDTL"),
    ENTITY_CANCEL_PURCHASE_ORDER: ("XP", "XPDTL"),
    ENTITY_CONSIGNMENT: ("Consignment", "ConsignmentDTL"),
    ENTITY_CONSIGNMENT_RETURN: ("ConsignmentReturn", "ConsignmentReturnDTL"),
}

MODELS = {
    ENTITY_CANCEL_SALES_ORDER: CanonicalCancelSalesOrder,
    ENTITY_CANCEL_PURCHASE_ORDER: CanonicalCancelPurchaseOrder,
    ENTITY_CONSIGNMENT: CanonicalConsignment,
    ENTITY_CONSIGNMENT_RETURN: CanonicalConsignmentReturn,
}

ALL = list(LINKED_DOCUMENT_ENTITY_TYPES)


# ── registration ─────────────────────────────────────────────────────────────


def test_the_four_entity_types_are_exactly_the_linked_document_set():
    assert set(LINKED_DOCUMENT_ENTITY_TYPES) == set(SEGMENTS)
    for entity_type in ALL:
        assert entity_type in DOCUMENT_ENTITY_TYPES
        assert is_document_entity(entity_type)


@pytest.mark.parametrize("entity_type", ALL)
def test_each_entity_is_registered_in_every_catalogue(entity_type):
    assert entity_type in ETL_ENTITY_TYPES
    assert entity_type in ENTITY_PROFILES
    assert CANONICAL_MODELS[entity_type] is MODELS[entity_type]
    assert entity_type in DOCUMENT_PRESETS


@pytest.mark.parametrize("entity_type", ALL)
def test_the_flat_profile_carries_nested_prefixed_lines(entity_type):
    profile = flat_profile(entity_type, ["DocKey"])
    assert profile.record_model is MODELS[entity_type]
    assert profile.line_model is CanonicalLinkedDocumentLine
    assert profile.line_ref_prefix is True
    # No fulfilment aggregate: a cancel/consignment line has no "delivered"
    # quantity, and guessing one would feed a wrong `lines.open_count`.
    assert profile.line_fulfilled_field is None


def test_the_existing_order_documents_are_unchanged():
    """Kill test: the new set must never swallow or reorder the order family."""
    assert DOCUMENT_ENTITY_TYPES[:3] == (
        ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER,
    )
    assert not set(LINKED_DOCUMENT_ENTITY_TYPES) & {
        ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER,
    }


# ── wire shape: the DO/GRN doc-feed record (golden) ─────────────────────────

BOOK = "db1"


def _raw_row(**overrides) -> dict:
    """A fake XS header row exactly as `SqlDbSource` hands it to the mapper:
    driver types (Decimal, naive datetime), the ESB-internal join/fingerprint
    columns, and its lines nested under `_lines`."""
    row = {
        "DocKey": 51234, "DocNo": "XS-000123",
        "DocDate": datetime(2026, 10, 1), "DebtorAutoKey": 300,
        "DebtorCode": "300-A001", "DebtorName": "Acme Sdn Bhd", "SalesAgent": "JOHN",
        "Ref": "R-1", "Description": "Cancel", "RefDocNo": None, "CurrencyCode": "MYR",
        "Note": "free text", "Cancelled": "F",
        "LastModified": datetime(2026, 10, 1, 9, 0, 0, 120000),
        "LineCount": 1, "QtySum": Decimal("2.00000000"), "SubTotalSum": Decimal("300.00"),
        "MaxDtlKey": 998877, "LinkedLineCount": 0, "FromDocKeySum": None,
        "_lines": [_fake_line()],
    }
    row.update(overrides)
    return row


def _fake_line(**overrides) -> dict:
    line = {
        "DocKey": 51234, "DtlKey": 998877, "Seq": 1, "ItemAutoKey": 10442,
        "ItemCode": "CHAIR-01", "Description": "Office chair", "LocationAutoKey": 7,
        "Location": "HQ", "Qty": Decimal("2.00000000"), "UOM": "UNIT",
        "UnitPrice": Decimal("150.50000000"), "SubTotal": Decimal("301.00"),
        "FromDocType": "SO", "FromDocNo": "SO-000456", "FromDocDtlKey": None,
    }
    line.update(overrides)
    return line


GOLDEN_RECORD = {
    "DocKey": 51234, "DocNo": "XS-000123", "DocDate": "2026-10-01T00:00:00.000",
    "DebtorCode": "300-A001", "DebtorName": "Acme Sdn Bhd", "SalesAgent": "JOHN",
    "Ref": "R-1", "Description": "Cancel", "RefDocNo": None, "CurrencyCode": "MYR",
    "Note": "free text", "Cancelled": "F", "LastModified": "2026-10-01T09:00:00.120",
    "Details": [{
        "DocKey": 51234, "DtlKey": 998877, "Seq": 1, "ItemCode": "CHAIR-01",
        "Description": "Office chair", "Location": "HQ", "Qty": 2, "UOM": "UNIT",
        "UnitPrice": 150.5, "SubTotal": 301, "FromDocType": "SO",
        "FromDocNo": "SO-000456", "FromDocDtlKey": None,
    }],
}


def _record(entity_type=ENTITY_CANCEL_SALES_ORDER, raw=None, **fields):
    raw = raw if raw is not None else _raw_row()
    return MODELS[entity_type](
        source_ref=linked_document_ref(entity_type, BOOK, raw["DocKey"]),
        doc_no=raw.get("DocNo"), source_record=raw, **fields,
    )


def test_the_wire_record_is_the_vendor_header_with_details():
    """CRM #1623 takes the DO/GRN doc-feed record: PascalCase AutoCount
    columns verbatim, lines under `Details`, the ESB's own join/fingerprint
    columns stripped, decimals as JSON numbers, datetimes as the vendor's
    naive `YYYY-MM-DDTHH:MM:SS.fff`."""
    payload = _record().sink_payload(contract_version=2)
    assert payload == GOLDEN_RECORD
    json.dumps(payload)  # wire-safe as is


def test_the_staged_json_round_trip_keeps_the_wire_values():
    """`canonical_json` is what the push rehydrates from - numbers must stay
    numbers through it, never become strings."""
    record = _record()
    rehydrated = CanonicalCancelSalesOrder(**record.model_dump(mode="json"))
    assert rehydrated.sink_payload() == GOLDEN_RECORD


def test_the_source_ref_is_the_crm_derivation_per_entity():
    assert {e: linked_document_ref(e, BOOK, 7) for e in ALL} == {
        ENTITY_CANCEL_SALES_ORDER: "db1:XS:7",
        ENTITY_CANCEL_PURCHASE_ORDER: "db1:XP:7",
        ENTITY_CONSIGNMENT: "db1:CG:7",
        ENTITY_CONSIGNMENT_RETURN: "db1:CR:7",
    }


def test_no_canonical_key_ever_reaches_the_wire():
    payload = _record(customer_code="300-A001", status="open").sink_payload()
    for key in ("source_ref", "doc_no", "customer_code", "status", "lines", "_lines"):
        assert key not in payload, key
    for internal in ("DebtorAutoKey", "LineCount", "QtySum", "SubTotalSum", "MaxDtlKey",
                     "LinkedLineCount", "FromDocKeySum"):
        assert internal not in payload, internal
    assert "ItemAutoKey" not in payload["Details"][0]
    assert "LocationAutoKey" not in payload["Details"][0]


def test_the_link_match_columns_ride_every_line():
    """FromDocDtlKey is often empty: the CRM matches by FromDocNo + item +
    location + qty, so all of them are on the line regardless."""
    line = _record().sink_payload()["Details"][0]
    for key in ("FromDocType", "FromDocNo", "FromDocDtlKey", "ItemCode", "Location", "Qty", "DocKey"):
        assert key in line, key


def test_a_header_without_lines_still_sends_details():
    payload = _record(raw=_raw_row(_lines=[])).sink_payload()
    assert payload["Details"] == []


def test_a_zero_quantity_is_a_number_not_dropped():
    raw = _raw_row(_lines=[_fake_line(Qty=Decimal("0E-8"), SubTotal=Decimal("0.00"))])
    line = _record(raw=raw).sink_payload()["Details"][0]
    assert line["Qty"] == 0 and line["SubTotal"] == 0


def test_status_stays_in_the_fixed_vocabulary():
    with pytest.raises(ValueError):
        CanonicalCancelSalesOrder(source_ref="r", doc_no="XS-1", status="voided")


def test_duplicate_line_refs_are_rejected():
    line = CanonicalLinkedDocumentLine(source_ref="r:1", product_code="A", qty=Decimal("1"))
    with pytest.raises(ValueError):
        CanonicalConsignmentReturn(source_ref="r", doc_no="CR-1", lines=[line, line])


def test_consignment_and_return_carry_the_customer():
    for model in (CanonicalConsignment, CanonicalConsignmentReturn):
        assert "customer_code" in model.SINK_FIELDS
        assert "supplier_code" not in model.SINK_FIELDS


# ── mapping catalogue ────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", ALL)
def test_catalog_requires_the_doc_number_and_the_crm_match_fields(entity_type):
    assert required_field_names(entity_type) == {"doc_no"}
    assert line_required_field_names(entity_type) == {"source_ref", "product_code", "qty"}
    assert "source_ref" not in accepted_field_names(entity_type)  # header ref is MINTED
    for field in ("from_doc_type", "from_doc_no", "from_doc_line_key", "warehouse_code"):
        assert field in line_accepted_field_names(entity_type)


@pytest.mark.parametrize("entity_type", ALL)
def test_catalog_offers_exactly_the_wire_fields(entity_type):
    model = MODELS[entity_type]
    assert accepted_field_names(entity_type) == set(model.SINK_FIELDS) - {"source_ref"}
    assert line_accepted_field_names(entity_type) == set(CanonicalLinkedDocumentLine.SINK_FIELDS)


# ── presets ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", ALL)
def test_preset_sql_reads_its_own_tables_and_binds_doc_key(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    header_table, line_table = TABLES[entity_type]
    assert f"FROM {{database}}.dbo.{header_table} AS h" in preset.header_query
    assert f"FROM {{database}}.dbo.{line_table} AS d" in preset.line_query
    assert f":{LINE_QUERY_DOC_KEY_PARAM}" in preset.line_query
    assert f"FROM {{database}}.dbo.{line_table} AS d" in preset.fingerprint_query
    assert ":from_date" in preset.fingerprint_query
    assert preset.key_columns == ("DocKey",)
    assert preset.watermark_column == "LastModified"
    assert preset.doc_date_column == "DocDate"
    # The SAME pseudo/display-line cut in the header aggregate and the line
    # fetch, or the LineCount guard reads a normal document as broken.
    cut = "d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    assert cut in preset.header_query and cut in preset.line_query
    for column in ("FromDocType", "FromDocNo", "FromDocDtlKey", "ItemCode", "Location", "Qty"):
        assert f"d.{column} AS {column}" in preset.line_query, column


def test_preset_sql_never_mixes_up_the_tables():
    """Kill test: a copy-paste that points one preset at a sibling's tables."""
    for entity_type, (header_table, line_table) in TABLES.items():
        preset = DOCUMENT_PRESETS[entity_type]
        for other, (other_header, other_line) in TABLES.items():
            if other == entity_type:
                continue
            assert f".dbo.{other_header} AS" not in preset.header_query
            assert f".dbo.{other_line} AS" not in preset.line_query


@pytest.mark.parametrize("entity_type", ALL)
def test_every_preset_row_targets_a_catalog_field(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    header_ok = accepted_field_names(entity_type)
    line_ok = line_accepted_field_names(entity_type)
    for row in preset.header:
        assert row.canonical_field in header_ok, row
    for row in preset.line:
        assert row.canonical_field in line_ok, row
    mapped_line = {row.canonical_field for row in preset.line}
    assert line_required_field_names(entity_type) <= mapped_line
    assert required_field_names(entity_type) <= {row.canonical_field for row in preset.header}


def test_party_columns_follow_the_document_side():
    debtor_side = (ENTITY_CANCEL_SALES_ORDER, ENTITY_CONSIGNMENT, ENTITY_CONSIGNMENT_RETURN)
    for entity_type in debtor_side:
        query = DOCUMENT_PRESETS[entity_type].header_query
        assert "h.DebtorCode AS DebtorCode" in query
        assert "Creditor" not in query
    query = DOCUMENT_PRESETS[ENTITY_CANCEL_PURCHASE_ORDER].header_query
    assert "h.CreditorCode AS CreditorCode" in query
    assert "Debtor" not in query


def _preset_engine(
    entity_type: str, *, status_formula: str = "", book: str = BOOK,
) -> MappingEngine:
    preset = DOCUMENT_PRESETS[entity_type]
    rows: List[MappingRow] = []
    for scope, fields in ((SCOPE_HEADER, preset.header), (SCOPE_LINE, preset.line)):
        for spec in fields:
            formula = spec.formula
            if status_formula and scope == SCOPE_HEADER and spec.canonical_field == "status":
                formula = status_formula
            rows.append(MappingRow(
                spec.source_path, spec.canonical_field, spec.transform, scope,
                is_required=spec.required, is_enabled=spec.enabled, formula=formula,
            ))
    return MappingEngine(
        rows, entity_type=entity_type,
        profile=flat_profile(entity_type, list(preset.key_columns)),
        # The identity scope of a linked document is the company's doc-feed
        # BOOK (`http_source.book.identity_scope`).
        database_name=book,
    )


def test_the_cancel_so_preset_maps_a_fake_row_end_to_end():
    """The preset rows validate the row (required doc_no / product_code /
    qty, status formula) and the record keeps the raw row for the wire, filed
    under the CRM's own ref `{book}:XS:{DocKey}`."""
    mapped = _preset_engine(ENTITY_CANCEL_SALES_ORDER).map_document(_raw_row())
    assert mapped.ok, [e.message() for e in mapped.errors]
    record = mapped.record
    assert record.source_ref == f"{BOOK}:XS:51234"
    assert record.doc_no == "XS-000123"
    assert record.status == "open"
    assert record.lines[0].product_code == "CHAIR-01"
    assert record.sink_payload() == GOLDEN_RECORD


def test_a_voided_cancel_document_maps_to_cancelled():
    raw = _raw_row(
        DocKey=1, DocNo="XP-1", CreditorAutoKey=400, PurchaseAgent="AMY", Cancelled="T",
        _lines=[_fake_line(DocKey=1, FromDocType="PO", FromDocNo="PO-1", FromDocDtlKey=55)],
    )
    mapped = _preset_engine(ENTITY_CANCEL_PURCHASE_ORDER).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.status == "cancelled"
    assert mapped.record.source_ref == f"{BOOK}:XP:1"
    assert mapped.record.agent_code == "AMY"
    line = mapped.record.sink_payload()["Details"][0]
    assert (line["FromDocType"], line["FromDocNo"], line["FromDocDtlKey"]) == ("PO", "PO-1", 55)


def test_a_hand_entered_consignment_maps_with_no_source_document():
    raw = _raw_row(DocKey=7, DocNo="CG-000001", _lines=[_fake_line(
        DocKey=7, FromDocType=None, FromDocNo=None,
    )])
    mapped = _preset_engine(ENTITY_CONSIGNMENT).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == f"{BOOK}:CG:7"
    line = mapped.record.sink_payload()["Details"][0]
    assert line["FromDocType"] is None and line["FromDocNo"] is None


def test_a_consignment_return_points_back_at_its_cg_document():
    raw = _raw_row(DocKey=8, DocNo="CR-000001", _lines=[_fake_line(
        DocKey=8, FromDocType="CG", FromDocNo="CG-000001",
    )])
    mapped = _preset_engine(ENTITY_CONSIGNMENT_RETURN).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == f"{BOOK}:CR:8"
    line = mapped.record.sink_payload()["Details"][0]
    assert (line["FromDocType"], line["FromDocNo"]) == ("CG", "CG-000001")


def test_an_unknown_book_is_a_named_identity_error_never_a_guess():
    engine = _preset_engine(ENTITY_CANCEL_SALES_ORDER, book="")
    mapped = engine.map_document(_raw_row())
    assert not mapped.ok
    assert any("book" in e.message() for e in mapped.errors)


def test_a_line_without_an_item_code_is_a_named_mapping_error():
    raw = _raw_row(DocKey=9, DocNo="XS-9", _lines=[_fake_line(DocKey=9, ItemCode=None)])
    mapped = _preset_engine(ENTITY_CANCEL_SALES_ORDER).map_document(raw)
    assert not mapped.ok
    assert any("product_code" in e.message() for e in mapped.errors)


# ── sink: path + contract-2.8 gate ───────────────────────────────────────────


@pytest.mark.parametrize("entity_type", ALL)
def test_each_entity_is_gated_on_contract_2_8_and_its_own_name(entity_type):
    segment = SEGMENTS[entity_type]
    assert LINKED_DOCUMENTS_CONTRACT_VERSION == 2.8
    assert CONTRACT_GATED_ENTITIES[entity_type] == (2.8, segment)
    assert sorento_supports_entity(entity_type) is False
    assert sorento_supports_entity(entity_type, contract_version=2.7, contract_entities=[segment]) is False
    assert sorento_supports_entity(entity_type, contract_version=2.8, contract_entities=["sales_orders"]) is False
    assert sorento_supports_entity(entity_type, contract_version=2.8, contract_entities=[segment]) is True
    assert entity_type.replace("_", " ") not in sorento_supported_entities_label()


@pytest.mark.parametrize("entity_type", ALL)
def test_each_entity_posts_the_doc_feed_envelope_to_its_own_route(entity_type):
    """`{companyCode, book, records}` to `/ingest/<plural>`; each record is
    the vendor-shaped row, and the CRM's verdict (keyed by its own
    `{book}:{CODE}:{DocKey}` derivation) is matched back to the record."""
    requests: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        code = {"cancel_sales_orders": "XS", "cancel_purchase_orders": "XP",
                "consignments": "CG", "consignment_returns": "CR"}[request.url.path.rsplit("/", 1)[-1]]
        records = [
            {"source_ref": f"{body['book']}:{code}:{r['DocKey']}", "outcome": "created", "entity_id": "id-1"}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": len(records), "created": len(records), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": records,
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=entity_type,
                       company_code="SOR", book=BOOK, transport=httpx.MockTransport(handle))
    [result] = sink.write_batch([_record(entity_type)], request_id="t")
    assert requests[0].url.path == f"/api/v1/external/ingest/{SEGMENTS[entity_type]}"
    body = json.loads(requests[0].content)
    assert body["book"] == BOOK and body["companyCode"] == "SOR"
    assert body["records"] == [GOLDEN_RECORD]
    assert result.delivered is True


def _with_doc_feed_book(db, company, book: str = BOOK) -> None:
    """The company's Delivery Orders feed row: the book the linked documents
    are filed under (`http_source.book.linked_document_book`)."""
    from modules.autocount.models import AcDocFeed

    db.add(AcDocFeed(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, feed="delivery_orders", book=book,
    ))
    db.commit()


def _staged(db, company_id, entity_type, *, job_status=None, op=None):
    from app.models.background_job import JOB_RUNNING, BackgroundJob
    from modules.autocount.models import STAGED_OP_DELETE

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=job_status or JOB_RUNNING,
        payload_json={"companyId": company_id, "entityType": entity_type},
    )
    db.add(job)
    db.commit()
    record = _record(entity_type)
    deleting = op == STAGED_OP_DELETE
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=entity_type,
        job_id=job.id, source_ref=record.source_ref, doc_no="D-1",
        raw_json=None if deleting else {"DocKey": 51234},
        canonical_json=None if deleting else record.model_dump(mode="json"),
        status=STAGED, **({"op": op} if op else {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, job


def test_the_identity_scope_of_a_linked_document_is_the_doc_feed_book(_stock_gate_rig):
    """`SqlDbSource.source_ref` (row hashes, delete intents) and the mapping
    engine both read `identity_scope`, so they always agree."""
    from modules.autocount.http_source.book import identity_scope

    db, company = _stock_gate_rig
    assert identity_scope(db, DEFAULT_TENANT_ID, company, ENTITY_CONSIGNMENT, None) == ""
    _with_doc_feed_book(db, company)
    assert identity_scope(db, DEFAULT_TENANT_ID, company, ENTITY_CONSIGNMENT, None) == BOOK
    # Every other entity keeps the company's database name.
    assert identity_scope(db, DEFAULT_TENANT_ID, company, ENTITY_SALES_ORDER, None) == company.database_name


def test_a_company_without_a_doc_feed_book_fails_closed_at_push(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.company_service import AutocountServiceError, CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    db, company = _stock_gate_rig
    with pytest.raises(AutocountServiceError, match="doc-feed book"):
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_CANCEL_SALES_ORDER)


@pytest.mark.parametrize("entity_type", ALL)
def test_sink_for_company_falls_back_to_logging_below_2_8(monkeypatch, _stock_gate_rig, entity_type):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.7, entities=[SEGMENTS[entity_type]]),
    )
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, entity_type)
    assert sink.name == SINK_LOGGING


def test_sink_for_company_opens_at_2_8_with_the_entity_advertised(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_CONSIGNMENT)
    assert isinstance(sink, SorentoSink)
    assert sink.book == BOOK


@pytest.mark.parametrize("entity_type", ALL)
def test_auto_push_refuses_a_shut_gate_and_leaves_rows_staged(monkeypatch, _stock_gate_rig, entity_type):
    """Kill test for silent loss: below 2.8 the company sink falls back to
    logging, which would mark the rows PUSHED while nothing reached the CRM -
    and change detection would never offer them again."""
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.7, entities=["sales_orders"]),
    )
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    row, job = _staged(db, company.id, entity_type)
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, entity_type, job_id=job.id)
    assert summary.get("errorCode") == "CONTRACT_GATE", summary
    assert "2.8" in summary.get("error", "")
    db.refresh(row)
    assert row.status == STAGED


def test_the_task_view_contract_banner_knows_the_2_8_requirement():
    from modules.autocount.services.company_service import CompanyService

    for entity_type in ALL:
        assert CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[entity_type] == 2.8


@pytest.mark.parametrize("entity_type", ALL + ["stock_balance"])
def test_approve_refuses_a_shut_gate_and_leaves_rows_staged(monkeypatch, _stock_gate_rig, entity_type):
    """Review blocker: the manual approval is a delivery path too. Below 2.8
    it must refuse (409, batch back in review, rows STAGED) - never mark the
    rows PUSHED through the logging fallback. Stock shares the same hole."""
    from app.models.background_job import JOB_NEEDS_REVIEW
    from modules.autocount.services.sync_service import ContractGateRefused, SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.4, entities=["sales_orders"]),
    )
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    if entity_type == "stock_balance":
        row, job = _staged(db, company.id, ENTITY_CONSIGNMENT, job_status=JOB_NEEDS_REVIEW)
        row.entity_type = entity_type
        job.payload_json = {"companyId": company.id, "entityType": entity_type}
        db.commit()
    else:
        row, job = _staged(db, company.id, entity_type, job_status=JOB_NEEDS_REVIEW)

    with pytest.raises(ContractGateRefused) as excinfo:
        SyncService(db).approve(DEFAULT_TENANT_ID, job.id)
    assert excinfo.value.error_code == "CONTRACT_GATE"
    db.refresh(row)
    db.refresh(job)
    assert row.status == STAGED
    assert job.status == JOB_NEEDS_REVIEW


def test_approve_still_delivers_once_the_gate_opens(monkeypatch, _stock_gate_rig):
    """Control: at 2.8 with the path advertised, approval reaches the real sink."""
    from app.models.background_job import JOB_NEEDS_REVIEW
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    sent: List[str] = []

    def fake_write_batch(self, records, *, request_id, **_kwargs):
        from modules.autocount.sinks import WriteResult

        sent.extend(r.source_ref for r in records)
        return [WriteResult(ok=True, sink="sorento", delivered=True) for _ in records]

    monkeypatch.setattr(SorentoSink, "write_batch", fake_write_batch)
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    row, job = _staged(db, company.id, ENTITY_CANCEL_SALES_ORDER, job_status=JOB_NEEDS_REVIEW)
    SyncService(db).approve(DEFAULT_TENANT_ID, job.id)
    assert sent == [row.source_ref]


def test_a_header_formula_over_line_aggregates_runs_for_a_linked_document():
    """Review should-fix: the save gate offers `lines.*` to every document's
    header formulas, so the run must define them here too (qty-based, nothing
    fulfilled) - never a per-document "Unknown name 'lines.count'"."""
    engine = _preset_engine(
        ENTITY_CANCEL_SALES_ORDER,
        status_formula='if(lines.count == 0, "closed", if(lines.outstanding_sum > 0, "open", "closed"))',
    )
    raw = {"DocKey": 3, "DocNo": "XS-3", "Cancelled": "F", "_lines": [_fake_line()]}
    mapped = engine.map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.status == "open"
    empty = engine.map_document({"DocKey": 4, "DocNo": "XS-4", "Cancelled": "F", "_lines": []})
    assert empty.ok, [e.message() for e in empty.errors]
    assert empty.record.status == "closed"


def test_a_huge_note_is_cut_never_rejected():
    from modules.autocount.canonical.documents import NOTE_MAX_CHARS

    payload = _record(raw=_raw_row(Note="x" * (NOTE_MAX_CHARS + 500))).sink_payload()
    assert len(payload["Note"]) == NOTE_MAX_CHARS


@pytest.mark.parametrize("entity_type", ALL)
def test_a_deleted_document_goes_to_the_doc_keys_deletions_door(monkeypatch, _stock_gate_rig, entity_type):
    """Owner ruling: a cancel document deleted in AutoCount must lower the
    CRM's cancelled qty. Its staged delete intent is sent through the DO/GRN
    deletions body `{doc_date_from, doc_date_to, doc_keys}` and a
    `deleted` verdict (echoing the CRM's own ref) marks it PUSHED."""
    from modules.autocount.models import STAGED_OP_DELETE, STAGED_PUSHED
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    calls: List[dict] = []

    def fake_delete_doc_keys(self, doc_keys, *, doc_date_from, doc_date_to, dry_run=False, on_chunk=None):
        calls.append({"keys": list(doc_keys), "from": doc_date_from, "to": doc_date_to,
                      "path": self._path_segment, "book": self.book})
        code = {ENTITY_CANCEL_SALES_ORDER: "XS", ENTITY_CANCEL_PURCHASE_ORDER: "XP",
                ENTITY_CONSIGNMENT: "CG", ENTITY_CONSIGNMENT_RETURN: "CR"}[self.entity_type]
        return {"summary": {"total": 1, "deleted": 1},
                "records": [{"source_ref": f"{self.book}:{code}:{k}", "outcome": "deleted"} for k in doc_keys]}

    def no_ref_deletes(self, *_a, **_k):  # pragma: no cover - must never be called
        raise AssertionError("linked documents never use the source_refs deletions body")

    monkeypatch.setattr(SorentoSink, "delete_doc_keys", fake_delete_doc_keys)
    monkeypatch.setattr(SorentoSink, "delete_batch", no_ref_deletes)
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    row, job = _staged(db, company.id, entity_type, op=STAGED_OP_DELETE)

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, entity_type, job_id=job.id)
    assert summary.get("deletedHandled") == 1, summary
    [call] = calls
    assert call["keys"] == [51234]
    assert call["path"] == SEGMENTS[entity_type] and call["book"] == BOOK
    assert call["from"] == "2023-01-01"  # no task config: the delete floor
    assert len(call["to"]) == 10
    db.refresh(row)
    assert row.status == STAGED_PUSHED


def test_the_sql_source_keys_row_hashes_on_the_same_crm_ref(session_factory):
    """`SqlDbSource.source_ref` keys `ac_row_hash` and the reconcile's delete
    intents. It must mint the SAME `{book}:{CODE}:{DocKey}` the mapped record
    carries, or a change would never match its stored hash and a delete
    would carry a ref the CRM never issued."""
    from modules.autocount.models import AcEntityConfig, SOURCE_IMPL_SQL_DB
    from modules.autocount.sql_source.runtime import RUNTIME
    from modules.autocount.sql_source.source import SqlDbSource
    from tests.test_autocount_documents import (
        HEADER_QUERY, LINE_QUERY, _company, _ctx, _source_engine, _sql_connection,
    )

    db = session_factory()
    try:
        conn = _sql_connection(db, _source_engine())
        company = _company(db)
        _with_doc_feed_book(db, company)
        config = AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_CANCEL_SALES_ORDER, source_impl=SOURCE_IMPL_SQL_DB,
        )
        config.source_config = {
            "connectionId": conn.id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        }
        config.result_columns = ["doc_key", "doc_no", "status", "doc_date", "last_modified"]
        db.add(config)
        db.commit()
        source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CANCEL_SALES_ORDER)
        assert source.source_ref({"doc_key": "D001"}) == f"{BOOK}:XS:D001"
    finally:
        db.close()
        RUNTIME.dispose_all()
