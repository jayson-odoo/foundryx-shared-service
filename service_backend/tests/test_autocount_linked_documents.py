"""AC-CANCEL-PULL - Cancel SO / Cancel PO / Consignment / Consignment Return.

Four more AutoCount documents pulled through the existing DATABASE source
(``source_impl = sql_db``) exactly like SO/PO/SPO, and pushed to the CRM
behind contract 2.8. What is NEW and therefore pinned here:

* the WIRE is the DO/GRN doc-feed shape the CRM (#1623) already ingests:
  body ``{companyCode, book, records}``, each record the AutoCount header row
  under its own PascalCase column names with its lines in ``Details``,
  ``source_ref`` = the CRM's own ``{book}:{XS|XP|CSGN|CSGR}:{DocKey}``, and
  deletions by ``doc_keys``;
* the link columns ``FromDocType``/``FromDocNo``/``FromDocDtlKey`` ride every
  line with ``ItemCode``/``Location``/``Qty`` (``FromDocDtlKey`` is always NULL
  on XSDTL since Dec 2024 - facts in ``presets.py``; the CRM owns linking);
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
        ENTITY_CONSIGNMENT: "db1:CSGN:7",
        ENTITY_CONSIGNMENT_RETURN: "db1:CSGR:7",
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
    """FromDocDtlKey is always NULL on XSDTL since Dec 2024 (presets.py); the
    link triple and the line's item/location/qty ride every line verbatim so the
    CRM can apply its own linking rule."""
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
    assert mapped.record.source_ref == f"{BOOK}:CSGN:7"
    line = mapped.record.sink_payload()["Details"][0]
    assert line["FromDocType"] is None and line["FromDocNo"] is None


def test_a_consignment_return_points_back_at_its_cg_document():
    raw = _raw_row(DocKey=8, DocNo="CR-000001", _lines=[_fake_line(
        DocKey=8, FromDocType="CG", FromDocNo="CG-000001",
    )])
    mapped = _preset_engine(ENTITY_CONSIGNMENT_RETURN).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == f"{BOOK}:CSGR:8"
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
                "consignments": "CSGN", "consignment_returns": "CSGR"}[request.url.path.rsplit("/", 1)[-1]]
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
                ENTITY_CONSIGNMENT: "CSGN", ENTITY_CONSIGNMENT_RETURN: "CSGR"}[self.entity_type]
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


# ── review blockers: the REAL paged run, not hand-built engines ─────────────


def test_the_sql_source_keeps_vendor_values_for_linked_documents(session_factory):
    """Review blocker B2: `SqlDbSource` used to pass every fetched document
    through `json_safe` (Decimal -> "2.00000000", datetime -> isoformat), so
    the wire carried strings. A linked document keeps vendor values: the
    staged raw, once mapped, IS the golden wire record."""
    from modules.autocount.sql_source.source import SqlDbSource

    staged_raw = SqlDbSource._record_safe(  # the instance state it reads is entity_type only
        type("S", (), {"entity_type": ENTITY_CANCEL_SALES_ORDER})(), _raw_row(),
    )
    assert staged_raw["_lines"][0]["Qty"] == 2
    assert staged_raw["LastModified"] == "2026-10-01T09:00:00.120"
    assert _record(raw=staged_raw).sink_payload() == GOLDEN_RECORD
    # Every other document keeps `json_safe`, byte-identical to before.
    so_raw = SqlDbSource._record_safe(
        type("S", (), {"entity_type": ENTITY_SALES_ORDER})(), {"Qty": Decimal("2.0")},
    )
    assert so_raw == {"Qty": "2.0"}


def test_a_paged_run_stages_under_the_crm_ref_and_hashes_the_same_key(session_factory):
    """Review blocker B1: the watermarked (paged) run built its mapping engine
    under `database_name`, so the staged record said `AED:XS:1` while the row
    hash and the CRM said `db1:XS:1` - every verdict missed. Runs the real
    job end to end on a SQLite source."""
    import sqlalchemy as sa
    from sqlalchemy.pool import StaticPool

    from app.jobs.service import JobService
    from modules.autocount.models import (
        ETL_STATUS_ACTIVE, AcEntityConfig, AcRowHash, AcStagedRecord, SOURCE_IMPL_SQL_DB,
    )
    from modules.autocount.presets import seed_document_mapping
    from modules.autocount.sql_source.runtime import RUNTIME
    from tests.test_autocount_documents import _company, _sql_connection

    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE xs (DocKey INTEGER PRIMARY KEY, DocNo TEXT, DocDate TEXT, "
            "Cancelled TEXT, LastModified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE xsdtl (DtlKey INTEGER PRIMARY KEY, DocKey INTEGER, "
            "ItemCode TEXT, Location TEXT, Qty NUMERIC, FromDocType TEXT, FromDocNo TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO xs VALUES (1, 'XS-000001', '2026-10-01', 'F', '2026-10-01 09:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO xsdtl VALUES (11, 1, 'CHAIR-01', 'HQ', 2, 'SO', 'SO-000456')"
        )

    db = session_factory()
    try:
        sql_conn = _sql_connection(db, engine)
        company = _company(db)
        _with_doc_feed_book(db, company)
        config = AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_CANCEL_SALES_ORDER, source_impl=SOURCE_IMPL_SQL_DB,
        )
        config.source_config = {
            "connectionId": sql_conn.id,
            "query": "SELECT DocKey, DocNo, DocDate, Cancelled, LastModified FROM xs",
            "lineQuery": (
                "SELECT DocKey, DtlKey, ItemCode, Location, Qty, FromDocType, FromDocNo "
                "FROM xsdtl WHERE DocKey = :doc_key"
            ),
            "keyColumns": ["DocKey"], "watermarkColumn": "LastModified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "DocDate",
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        }
        config.result_columns = ["DocKey", "DocNo", "DocDate", "Cancelled", "LastModified"]
        config.line_result_columns = [
            "DocKey", "DtlKey", "ItemCode", "Location", "Qty", "FromDocType", "FromDocNo",
        ]
        config.etl_status = ETL_STATUS_ACTIVE
        db.add(config)
        db.commit()
        seed_document_mapping(
            db, DEFAULT_TENANT_ID, company.id, ENTITY_CANCEL_SALES_ORDER,
            header_columns=None, line_columns=None,
        )
        db.commit()

        JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": company.id, "entityType": ENTITY_CANCEL_SALES_ORDER,
                     "mode": "incremental"},
        )
        staged = (
            db.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == company.id,
                    AcStagedRecord.entity_type == ENTITY_CANCEL_SALES_ORDER)
            .all()
        )
        hashes = {
            h.source_ref for h in db.query(AcRowHash).filter(
                AcRowHash.company_id == company.id,
                AcRowHash.entity_type == ENTITY_CANCEL_SALES_ORDER,
            )
        }
        assert [row.source_ref for row in staged] == [f"{BOOK}:XS:1"], [
            (row.source_ref, row.status, row.error) for row in staged
        ]
        assert hashes == {f"{BOOK}:XS:1"}
        wire = CanonicalCancelSalesOrder(**staged[0].canonical_json).sink_payload()
        assert wire["DocNo"] == "XS-000001"
        assert wire["Details"][0]["FromDocNo"] == "SO-000456"
    finally:
        db.close()
        RUNTIME.dispose_all()


def _delete_rig(monkeypatch, _stock_gate_rig, entity_type, *, ref_book=BOOK, from_date=None):
    from modules.autocount.models import STAGED_OP_DELETE

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    calls: List[dict] = []

    def fake_delete_doc_keys(self, doc_keys, *, doc_date_from, doc_date_to, dry_run=False, on_chunk=None):
        calls.append({"keys": list(doc_keys), "from": doc_date_from, "book": self.book})
        return {"records": [
            {"source_ref": linked_document_ref(self.entity_type, self.book, k), "outcome": "deleted"}
            for k in doc_keys
        ]}

    monkeypatch.setattr(SorentoSink, "delete_doc_keys", fake_delete_doc_keys)
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    if from_date is not None:
        from modules.autocount.models import AcEntityConfig

        db.add(AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
            source_impl="sql_db", source_config={"fromDate": from_date},
        ))
        db.commit()
    row, job = _staged(db, company.id, entity_type, op=STAGED_OP_DELETE)
    row.source_ref = linked_document_ref(entity_type, ref_book, 51234)
    db.commit()
    return db, company, row, job, calls


def test_a_delete_filed_under_another_book_is_quarantined_never_sent(monkeypatch, _stock_gate_rig):
    """Security + review blocker: the deletions body names the CURRENT book
    and bare DocKeys, so a ref pushed under an OLD book would delete the
    CRM's live document of the same DocKey in the new book. It is quarantined
    with a named reason instead, and nothing is sent."""
    from modules.autocount.models import STAGED_FAILED
    from modules.autocount.services.sync_service import SyncService

    db, company, row, job, calls = _delete_rig(
        monkeypatch, _stock_gate_rig, ENTITY_CONSIGNMENT, ref_book="oldbook",
    )
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CONSIGNMENT, job_id=job.id)
    assert calls == []
    db.refresh(row)
    assert row.status == STAGED_FAILED
    assert "different book" in summary["deleteFailures"][0]["error"]


@pytest.mark.parametrize("from_date,expected", [
    ("2026-01-01", "2026-01-01"),
    ("not-a-date", "2023-01-01"),
    ("", "2023-01-01"),
])
def test_the_delete_window_starts_at_a_valid_task_from_date(monkeypatch, _stock_gate_rig, from_date, expected):
    from modules.autocount.services.sync_service import SyncService

    db, company, _row, job, calls = _delete_rig(
        monkeypatch, _stock_gate_rig, ENTITY_CANCEL_PURCHASE_ORDER, from_date=from_date,
    )
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CANCEL_PURCHASE_ORDER, job_id=job.id)
    assert calls and calls[0]["from"] == expected


def test_below_2_8_the_gate_answers_before_the_missing_book(monkeypatch, _stock_gate_rig):
    """Review S2: a company below 2.8 with no doc-feed book still gets the
    logging fallback (so auto_push answers CONTRACT_GATE), never the book
    error with no error code."""
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.7, entities=["sales_orders"]),
    )
    db, company = _stock_gate_rig
    _row, job = _staged(db, company.id, ENTITY_CANCEL_SALES_ORDER)
    summary = SyncService(db).auto_push(
        DEFAULT_TENANT_ID, company.id, ENTITY_CANCEL_SALES_ORDER, job_id=job.id,
    )
    assert summary.get("errorCode") == "CONTRACT_GATE", summary


def test_the_missing_doc_feed_book_is_a_named_prerequisite():
    """Review S2 (foolproof-UI): the company detail warns before any push."""
    from modules.autocount.services.company_service import EntityState, document_prerequisites

    states = [EntityState.__new__(EntityState)]
    states[0].entity_type = ENTITY_CONSIGNMENT
    [line] = document_prerequisites(states, has_doc_feed_book=False)
    assert "delivery_orders" in line.inactive
    [line] = document_prerequisites(states, has_doc_feed_book=True)
    assert "delivery_orders" not in line.inactive


def test_the_company_detail_endpoint_names_the_missing_doc_feed_book(client, session_factory):
    """Review: the prerequisite is wired through the real detail route (not
    only the pure function), and clears once the DO feed has a book."""
    from modules.autocount.models import AcEntityConfig
    from tests.test_autocount_db_company import _auth
    from tests.test_autocount_documents import _company

    db = session_factory()
    company = _company(db)
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_CONSIGNMENT, source_impl="sql_db",
    ))
    db.commit()
    headers = _auth(client)

    def consignment_line():
        body = client.get(f"/autocount/companies/{company.id}", headers=headers).json()
        return next(
            p for p in body["company"]["documentPrerequisites"]
            if p["entityType"] == ENTITY_CONSIGNMENT
        )

    try:
        assert "delivery_orders" in consignment_line()["inactive"]
        _with_doc_feed_book(db, company)
        assert "delivery_orders" not in consignment_line()["inactive"]
    finally:
        db.close()


def test_deletes_go_out_per_chunk_and_keep_earlier_marks_on_a_later_failure(
    monkeypatch, _stock_gate_rig,
):
    """Review S3: one `delete_doc_keys` call per `batch_size` chunk, each
    chunk's verdicts committed before the next is sent - a failure on chunk 2
    never undoes chunk 1."""
    from modules.autocount.models import STAGED_OP_DELETE, STAGED_PUSHED
    from modules.autocount.services.sync_service import SyncService

    db, company, first, job, _calls = _delete_rig(monkeypatch, _stock_gate_rig, ENTITY_CONSIGNMENT)
    second = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_CONSIGNMENT,
        job_id=job.id, source_ref=linked_document_ref(ENTITY_CONSIGNMENT, BOOK, 99999),
        doc_no="D-2", status=STAGED, op=STAGED_OP_DELETE,
    )
    db.add(second)
    db.commit()
    calls: List[List[int]] = []

    def chunked(self, doc_keys, *, doc_date_from, doc_date_to, dry_run=False, on_chunk=None):
        calls.append(list(doc_keys))
        if len(calls) == 2:
            raise RuntimeError("consumer went away on chunk 2")
        return {"records": [
            {"source_ref": linked_document_ref(self.entity_type, self.book, k), "outcome": "deleted"}
            for k in doc_keys
        ]}

    monkeypatch.setattr(SorentoSink, "delete_doc_keys", chunked)
    real_init = SorentoSink.__init__

    def one_per_chunk(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self.batch_size = 1

    monkeypatch.setattr(SorentoSink, "__init__", one_per_chunk)
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CONSIGNMENT, job_id=job.id)
    assert calls == [[51234], [99999]]
    db.refresh(first)
    db.refresh(second)
    assert first.status == STAGED_PUSHED
    assert second.status == STAGED


def test_a_paged_run_stages_vendor_values_from_real_driver_types(session_factory):
    """Review blocker K-B2: the end-to-end run must carry DRIVER types
    (Decimal / datetime, as SQL Server returns them) through `SqlDbSource`
    into the staged record - a `json_safe` call site would turn them into
    strings on the wire. SQLite is told to return those types here."""
    import sqlite3

    import sqlalchemy as sa
    from sqlalchemy.pool import StaticPool

    from app.jobs.service import JobService
    from modules.autocount.models import ETL_STATUS_ACTIVE, AcEntityConfig, SOURCE_IMPL_SQL_DB
    from modules.autocount.presets import seed_document_mapping
    from modules.autocount.sql_source.runtime import RUNTIME
    from tests.test_autocount_documents import _company, _sql_connection

    sqlite3.register_converter("DECIMAL", lambda raw: Decimal(raw.decode()))
    engine = sa.create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False, "detect_types": sqlite3.PARSE_DECLTYPES},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE cg (DocKey INTEGER PRIMARY KEY, DocNo TEXT, DocDate TIMESTAMP, "
            "Cancelled TEXT, LastModified TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE cgdtl (DtlKey INTEGER PRIMARY KEY, DocKey INTEGER, ItemCode TEXT, "
            "Location TEXT, Qty DECIMAL, UnitPrice DECIMAL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO cg VALUES (1, 'CG-000001', '2026-10-01 00:00:00', 'F', "
            "'2026-10-01 09:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO cgdtl VALUES (11, 1, 'CHAIR-01', 'HQ', '2.00000000', '150.50000000')"
        )
        sample = conn.exec_driver_sql("SELECT Qty, LastModified FROM cg JOIN cgdtl USING (DocKey)").one()
    assert isinstance(sample[0], Decimal) and isinstance(sample[1], datetime)

    db = session_factory()
    try:
        sql_conn = _sql_connection(db, engine)
        company = _company(db)
        _with_doc_feed_book(db, company)
        config = AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_CONSIGNMENT, source_impl=SOURCE_IMPL_SQL_DB,
        )
        config.source_config = {
            "connectionId": sql_conn.id,
            "query": "SELECT DocKey, DocNo, DocDate, Cancelled, LastModified FROM cg",
            "lineQuery": (
                "SELECT DocKey, DtlKey, ItemCode, Location, Qty, UnitPrice "
                "FROM cgdtl WHERE DocKey = :doc_key"
            ),
            "keyColumns": ["DocKey"], "watermarkColumn": "LastModified",
            "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "DocDate",
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        }
        config.result_columns = ["DocKey", "DocNo", "DocDate", "Cancelled", "LastModified"]
        config.line_result_columns = ["DocKey", "DtlKey", "ItemCode", "Location", "Qty", "UnitPrice"]
        config.etl_status = ETL_STATUS_ACTIVE
        db.add(config)
        db.commit()
        seed_document_mapping(
            db, DEFAULT_TENANT_ID, company.id, ENTITY_CONSIGNMENT,
            header_columns=None, line_columns=None,
        )
        db.commit()
        JobService(db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": company.id, "entityType": ENTITY_CONSIGNMENT, "mode": "incremental"},
        )
        [staged] = (
            db.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == company.id,
                    AcStagedRecord.entity_type == ENTITY_CONSIGNMENT)
            .all()
        )
        wire = CanonicalConsignment(**staged.canonical_json).sink_payload()
        assert wire["LastModified"] == "2026-10-01T09:00:00.000", wire
        assert wire["DocDate"] == "2026-10-01T00:00:00.000", wire
        line = wire["Details"][0]
        assert line["Qty"] == 2 and isinstance(line["Qty"], int), line
        assert line["UnitPrice"] == 150.5, line

        # The fingerprint sweep's keyed re-fetch is the OTHER path a staged
        # document is built on - same vendor values.
        from modules.autocount.sql_source.source import SqlDbSource
        from tests.test_autocount_documents import _ctx

        db.refresh(config)
        source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CONSIGNMENT)
        try:
            refetched = [r.raw for r in source.fetch_by_keys([1]).records]
        finally:
            source.close()
        assert refetched, "the keyed re-fetch returned nothing to check"
        assert refetched[0]["LastModified"] == "2026-10-01T09:00:00.000"
        assert refetched[0]["_lines"][0]["Qty"] == 2
    finally:
        db.close()
        RUNTIME.dispose_all()


@pytest.mark.parametrize("tail", ["0012", "١٢", "12abc"])
def test_a_non_canonical_doc_key_is_quarantined_never_aliased(monkeypatch, _stock_gate_rig, tail):
    """`0012` must never alias DocKey 12, nor non-ASCII digits parse."""
    from modules.autocount.models import STAGED_FAILED
    from modules.autocount.services.sync_service import SyncService

    db, company, row, job, calls = _delete_rig(monkeypatch, _stock_gate_rig, ENTITY_CONSIGNMENT)
    row.source_ref = f"{linked_document_ref(ENTITY_CONSIGNMENT, BOOK, '')}{tail}"
    db.commit()
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CONSIGNMENT, job_id=job.id)
    assert calls == []
    db.refresh(row)
    assert row.status == STAGED_FAILED


def test_a_future_from_date_never_inverts_the_delete_window(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.sync_service import SyncService

    db, company, _row, job, _calls = _delete_rig(
        monkeypatch, _stock_gate_rig, ENTITY_CANCEL_SALES_ORDER, from_date="2099-01-01",
    )
    seen: List[tuple] = []

    def capture(self, doc_keys, *, doc_date_from, doc_date_to, dry_run=False, on_chunk=None):
        seen.append((doc_date_from, doc_date_to))
        return {"records": []}

    monkeypatch.setattr(SorentoSink, "delete_doc_keys", capture)
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CANCEL_SALES_ORDER, job_id=job.id)
    [(start, end)] = seen
    assert start == end


def test_the_ref_codes_match_the_crm():
    """CRM #1623 mints these itself from the envelope `book` + `DocKey`
    (`autocount_cancel_ingest_service.py` `_PREFIX` / `_source_ref`, confirmed
    by the crew at CRM head 431a030d) and answers verdicts under them. A
    mismatch makes every verdict miss and quarantines every delete as
    wrong-book - so all four are pinned verbatim here, NOT AutoCount's own
    `CG`/`CR`."""
    from modules.autocount.canonical.documents import LINKED_DOCUMENT_REF_CODES

    assert LINKED_DOCUMENT_REF_CODES == {
        ENTITY_CANCEL_SALES_ORDER: "XS",
        ENTITY_CANCEL_PURCHASE_ORDER: "XP",
        ENTITY_CONSIGNMENT: "CSGN",
        ENTITY_CONSIGNMENT_RETURN: "CSGR",
    }
