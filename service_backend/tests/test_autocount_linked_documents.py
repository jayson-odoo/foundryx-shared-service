"""AC-CANCEL-PULL - Cancel SO / Cancel PO / Consignment / Consignment Return.

Four more AutoCount documents pulled through the existing DATABASE source
(``source_impl = sql_db``) exactly like SO/PO/SPO, and pushed to the CRM
behind contract 2.8. What is NEW and therefore pinned here:

* the four canonical shapes and their wire payload (golden, every optional
  field OMITTED when empty - never an explicit ``null``);
* the link fields (``from_doc_type``/``from_doc_no``/``from_doc_line_key``) -
  ``FromDocDtlKey`` is empty on every line since ~Oct-Nov 2024, so the CRM
  matches on ``from_doc_no`` + ``product_code`` + ``warehouse_code`` + ``qty``
  and all four must ride the line;
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


# ── canonical wire shape (golden) ────────────────────────────────────────────


def _full_line(**overrides) -> CanonicalLinkedDocumentLine:
    data = dict(
        source_ref=f"{DB}:51234:998877",
        line_number=1,
        product_ref=f"{DB}:10442",
        product_code="CHAIR-01",
        product_name="Office chair",
        warehouse_ref=f"{DB}:7",
        warehouse_code="HQ",
        qty=Decimal("2"),
        uom="UNIT",
        unit_price=Decimal("150.00"),
        line_total=Decimal("300.00"),
        from_doc_type="SO",
        from_doc_no="SO-000456",
        from_doc_line_key=445566,
    )
    data.update(overrides)
    return CanonicalLinkedDocumentLine(**data)


GOLDEN_LINE = {
    "source_ref": f"{DB}:51234:998877",
    "line_number": 1,
    "product_ref": f"{DB}:10442",
    "product_code": "CHAIR-01",
    "product_name": "Office chair",
    "warehouse_ref": f"{DB}:7",
    "warehouse_code": "HQ",
    "qty": "2",
    "uom": "UNIT",
    "unit_price": "150.00",
    "line_total": "300.00",
    "from_doc_type": "SO",
    "from_doc_no": "SO-000456",
    "from_doc_line_key": 445566,
}


def test_cancel_sales_order_payload_is_exactly_the_agreed_shape():
    record = CanonicalCancelSalesOrder(
        source_ref=f"{DB}:51234", doc_no="XS-000123", doc_date="2026-10-01",
        status="open", customer_ref=f"{DB}:300", customer_code="300-A001",
        customer_name="Acme Sdn Bhd", agent_code="JOHN", ref="R-1", note="free text",
        lines=[_full_line()],
    )
    assert record.sink_payload(contract_version=2) == {
        "source_ref": f"{DB}:51234",
        "doc_no": "XS-000123",
        "doc_date": "2026-10-01",
        "status": "open",
        "customer_ref": f"{DB}:300",
        "customer_code": "300-A001",
        "customer_name": "Acme Sdn Bhd",
        "agent_code": "JOHN",
        "ref": "R-1",
        "note": "free text",
        "lines": [GOLDEN_LINE],
    }


def test_cancel_purchase_order_carries_the_supplier_not_the_customer():
    record = CanonicalCancelPurchaseOrder(
        source_ref=f"{DB}:9", doc_no="XP-000001", status="cancelled",
        supplier_ref=f"{DB}:400", supplier_code="400-S001", supplier_name="Supply Co",
        lines=[_full_line(from_doc_type="PO", from_doc_no="PO-000010")],
    )
    payload = record.sink_payload(contract_version=2)
    assert payload["supplier_code"] == "400-S001"
    assert not any(key.startswith("customer_") for key in payload)
    assert payload["status"] == "cancelled"
    assert payload["lines"][0]["from_doc_type"] == "PO"


def test_consignment_and_return_carry_the_customer():
    for model in (CanonicalConsignment, CanonicalConsignmentReturn):
        assert "customer_code" in model.SINK_FIELDS
        assert "supplier_code" not in model.SINK_FIELDS


def test_empty_optional_fields_are_omitted_never_sent_as_null():
    """A consignment (CG-) is entered by hand: no source doc, so no from_*
    on the wire at all, and an unset header field is absent, not null."""
    record = CanonicalConsignment(
        source_ref=f"{DB}:77", doc_no="CG-000001",
        lines=[_full_line(
            from_doc_type=None, from_doc_no="", from_doc_line_key=None,
            product_ref=None, unit_price=None,
        )],
    )
    payload = record.sink_payload(contract_version=2)
    assert payload == {
        "source_ref": f"{DB}:77",
        "doc_no": "CG-000001",
        "lines": [payload["lines"][0]],
    }
    line = payload["lines"][0]
    for absent in ("from_doc_type", "from_doc_no", "from_doc_line_key", "product_ref", "unit_price"):
        assert absent not in line, absent
    assert None not in line.values()


def test_link_match_fields_survive_an_empty_from_doc_dtl_key():
    """FromDocDtlKey is EMPTY since ~Oct-Nov 2024 - the CRM then matches by
    from_doc_no + product_code + warehouse_code + qty, so all four must still
    be on the line."""
    line = _full_line(from_doc_line_key=None).sink_payload(contract_version=2)
    assert "from_doc_line_key" not in line
    for kept in ("from_doc_no", "product_code", "warehouse_code", "qty"):
        assert line[kept] is not None, kept


def test_a_zero_quantity_is_a_real_value_not_an_empty_one():
    """Kill test: the omit-when-empty rule must never drop a genuine 0."""
    line = _full_line(
        qty=Decimal("0"), line_total=Decimal("0"), line_number=0, from_doc_line_key=0,
    ).sink_payload(contract_version=2)
    assert line["qty"] == "0"
    assert line["line_total"] == "0"
    assert line["line_number"] == 0
    assert line["from_doc_line_key"] == 0


def test_the_payload_ignores_the_connection_contract_version():
    """These four are gated on the consumer's live contract (2.8) instead -
    the v1/v2 fallback split never applies, so nothing disappears at v1."""
    record = CanonicalCancelSalesOrder(
        source_ref=f"{DB}:1", doc_no="XS-1", customer_code="C", lines=[_full_line()],
    )
    assert record.sink_payload(contract_version=1) == record.sink_payload(contract_version=2)


def test_status_stays_in_the_fixed_vocabulary():
    with pytest.raises(ValueError):
        CanonicalCancelSalesOrder(source_ref="r", doc_no="XS-1", status="voided")


def test_duplicate_line_refs_are_rejected():
    with pytest.raises(ValueError):
        CanonicalConsignmentReturn(
            source_ref="r", doc_no="CR-1", lines=[_full_line(), _full_line()],
        )


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


def _preset_engine(entity_type: str, *, status_formula: str = "") -> MappingEngine:
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
        database_name=DB,
    )


def _fake_line(**overrides) -> dict:
    line = {
        "DtlKey": 998877, "Seq": 1, "ItemAutoKey": 10442, "ItemCode": "CHAIR-01",
        "Description": "Office chair", "LocationAutoKey": 7, "Location": "HQ",
        "Qty": Decimal("2"), "UOM": "UNIT", "UnitPrice": Decimal("150.00"),
        "SubTotal": Decimal("300.00"), "FromDocType": "SO", "FromDocNo": "SO-000456",
        "FromDocDtlKey": None,
    }
    line.update(overrides)
    return line


def test_the_cancel_so_preset_maps_a_fake_row_end_to_end():
    raw = {
        "DocKey": 51234, "DocNo": "XS-000123", "DocDate": "2026-10-01",
        "DebtorAutoKey": 300, "DebtorCode": "300-A001", "DebtorName": "Acme Sdn Bhd",
        "SalesAgent": "JOHN", "Ref": "R-1", "Note": "free text", "Cancelled": "F",
        "LastModified": "2026-10-01 09:00:00", "LineCount": 1,
        "_lines": [_fake_line()],
    }
    mapped = _preset_engine(ENTITY_CANCEL_SALES_ORDER).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    payload = mapped.record.sink_payload(contract_version=2)
    assert payload["source_ref"] == f"{DB}:51234"
    assert payload["doc_no"] == "XS-000123"
    assert payload["status"] == "open"
    assert payload["customer_ref"] == f"{DB}:300"
    [line] = payload["lines"]
    assert line["source_ref"] == f"{DB}:51234:998877"
    assert line["product_ref"] == f"{DB}:10442"
    assert line["warehouse_code"] == "HQ"
    assert line["from_doc_no"] == "SO-000456"
    assert "from_doc_line_key" not in line


def test_a_voided_cancel_document_maps_to_cancelled():
    raw = {
        "DocKey": 1, "DocNo": "XP-1", "CreditorAutoKey": 400, "Cancelled": "T",
        "_lines": [_fake_line(FromDocType="PO", FromDocNo="PO-1", FromDocDtlKey=55)],
    }
    mapped = _preset_engine(ENTITY_CANCEL_PURCHASE_ORDER).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.status == "cancelled"
    assert mapped.record.supplier_ref == f"{DB}:400"
    assert mapped.record.lines[0].from_doc_line_key == 55


def test_a_hand_entered_consignment_maps_with_no_source_document():
    raw = {
        "DocKey": 7, "DocNo": "CG-000001", "DebtorCode": "300-A001", "Cancelled": "F",
        "_lines": [_fake_line(FromDocType=None, FromDocNo=None)],
    }
    mapped = _preset_engine(ENTITY_CONSIGNMENT).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload(contract_version=2)["lines"][0]
    assert "from_doc_type" not in line and "from_doc_no" not in line


def test_a_consignment_return_points_back_at_its_cg_document():
    raw = {
        "DocKey": 8, "DocNo": "CR-000001", "DebtorCode": "300-A001", "Cancelled": "F",
        "_lines": [_fake_line(FromDocType="CG", FromDocNo="CG-000001")],
    }
    mapped = _preset_engine(ENTITY_CONSIGNMENT_RETURN).map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload(contract_version=2)["lines"][0]
    assert (line["from_doc_type"], line["from_doc_no"]) == ("CG", "CG-000001")


def test_a_line_without_an_item_code_is_a_named_mapping_error():
    raw = {"DocKey": 9, "DocNo": "XS-9", "_lines": [_fake_line(ItemCode=None)]}
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
def test_each_entity_posts_to_its_own_plural_ingest_route(entity_type):
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
    record = MODELS[entity_type](source_ref="ref-1", doc_no="D-1", lines=[_full_line()])
    result = sink.write_batch([record], request_id="t")
    assert requests[0].url.path == f"/api/v1/external/ingest/{SEGMENTS[entity_type]}"
    sent = json.loads(requests[0].content)["records"][0]
    assert sent["lines"][0]["from_doc_no"] == "SO-000456"
    assert result is not None


def _staged(db, company_id, entity_type, *, job_status=None):
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=job_status or JOB_RUNNING,
        payload_json={"companyId": company_id, "entityType": entity_type},
    )
    db.add(job)
    db.commit()
    record = MODELS[entity_type](source_ref=f"{DB}:1", doc_no="D-1", lines=[_full_line()])
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=entity_type,
        job_id=job.id, source_ref=record.source_ref, doc_no="D-1",
        raw_json={"DocKey": 1}, canonical_json=record.model_dump(mode="json"),
        status=STAGED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, job


@pytest.mark.parametrize("entity_type", ALL)
def test_sink_for_company_falls_back_to_logging_below_2_8(monkeypatch, _stock_gate_rig, entity_type):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.7, entities=[SEGMENTS[entity_type]]),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, entity_type)
    assert sink.name == SINK_LOGGING


def test_sink_for_company_opens_at_2_8_with_the_entity_advertised(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.8, entities=list(SEGMENTS.values())),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_CONSIGNMENT)
    assert isinstance(sink, SorentoSink)


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

    record = CanonicalConsignment(source_ref="r", doc_no="CG-1", note="x" * (NOTE_MAX_CHARS + 500))
    assert len(record.sink_payload()["note"]) == NOTE_MAX_CHARS
    assert record.sink_payload()["lines"] == []
