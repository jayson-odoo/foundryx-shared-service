"""Plan 32 (lane SS-BILLING-FEED, CRM #1770) - billing documents + AR outstanding.

Four AutoCount billing documents (IV, CS, CN, DN) pulled through the existing
DATABASE source exactly like SO/PO and the linked documents, and pushed to the
CRM's ONE `billing_documents` door (contract 2.6, section 12); plus one AR
outstanding snapshot per debtor pushed to `ar_outstanding` (contract 2.10,
section 14). Contract copy: `documentation/plans/sprint-5/32-*-contract.md`.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    AR_OUTSTANDING_REF_MARKER,
    BILLING_DOCUMENT_ENTITY_TYPES,
    BILLING_DOCUMENT_REF_CODES,
    DOCUMENT_ENTITY_TYPES,
    ENTITY_AR_OUTSTANDING,
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
    LINE_QUERY_DOC_KEY_PARAM,
    LINKED_DOCUMENT_ENTITY_TYPES,
    ORDER_DOCUMENT_ENTITY_TYPES,
    CanonicalArOutstanding,
    CanonicalBillingDocument,
    is_document_entity,
)
from modules.autocount.mapping import (
    ENTITY_PROFILES,
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    flat_profile,
    flat_source_ref,
)
from modules.autocount.mapping_catalog import (
    accepted_field_names,
    line_accepted_field_names,
    line_required_field_names,
    required_field_names,
)
from modules.autocount.models import STAGED, AcStagedRecord
from modules.autocount.presets import DOCUMENT_PRESETS
from modules.autocount.services.company_service import DOCUMENT_PREREQUISITES
from modules.autocount.services.etl_service import ETL_ENTITY_TYPES
from modules.autocount.services.sync_service import CANONICAL_MODELS
from modules.autocount.sinks import SINK_LOGGING
from modules.autocount.sinks_sorento import (
    AR_OUTSTANDING_CONTRACT_VERSION,
    BILLING_DOCUMENTS_CONTRACT_VERSION,
    CONTRACT_GATED_ENTITIES,
    PUSH_REFUSES_LOGGING_FALLBACK,
    ContractVersion,
    SorentoContractInfo,
    SorentoSink,
    sorento_supports_entity,
)
from modules.autocount.sync import AUTOCOUNT_SYNC, NO_DELETION_ENTITY_TYPES

from tests.test_s13_stock_push_contract_gate import _stock_gate_rig  # noqa: F401

DB = "FAKE_DB"
BOOK = "fakebook"
MYT = timezone(timedelta(hours=8))

TABLES: Dict[str, tuple] = {
    ENTITY_INVOICE: ("IV", "IVDTL"),
    ENTITY_CASH_SALE: ("CS", "CSDTL"),
    ENTITY_CREDIT_NOTE: ("CN", "CNDTL"),
    ENTITY_DEBIT_NOTE: ("DN", "DNDTL"),
}
CODES = {ENTITY_INVOICE: "IV", ENTITY_CASH_SALE: "CS", ENTITY_CREDIT_NOTE: "CN", ENTITY_DEBIT_NOTE: "DN"}
BILLING = list(BILLING_DOCUMENT_ENTITY_TYPES)
ALL_NEW = BILLING + [ENTITY_AR_OUTSTANDING]

HEADER_WIRE_KEYS = {
    "source_ref", "document_type", "doc_no", "doc_date", "status", "source_modified_at",
    "customer_ref", "customer_code", "customer_name", "agent_code", "currency_code",
    "currency_rate", "net_total", "tax_total", "total", "local_net_total", "against_doc_no",
    "against_source_ref", "ref", "description", "lines",
}
LINE_WIRE_KEYS = {
    "source_ref", "line_number", "product_ref", "product_code", "description", "uom",
    "quantity", "unit_price", "discount_amount", "net_amount", "tax_code", "tax_rate",
    "tax_amount", "line_total", "from_doc_type", "from_doc_no", "from_line_ref",
}


# ── A. contract versions (BL-SS-289) ─────────────────────────────────────────


def test_the_billing_and_ar_gates_are_2_6_and_2_10():
    assert BILLING_DOCUMENTS_CONTRACT_VERSION == ContractVersion(2, 6)
    assert AR_OUTSTANDING_CONTRACT_VERSION == ContractVersion(2, 10)
    assert AR_OUTSTANDING_CONTRACT_VERSION > ContractVersion(2, 9)
    for entity_type in BILLING:
        assert CONTRACT_GATED_ENTITIES[entity_type] == (ContractVersion(2, 6), "billing_documents")
    assert CONTRACT_GATED_ENTITIES[ENTITY_AR_OUTSTANDING] == (ContractVersion(2, 10), "ar_outstanding")


def test_ar_outstanding_opens_on_the_crm_string_2_10_and_not_on_2_9():
    v210 = ContractVersion.parse("2.10")
    v29 = ContractVersion.parse("2.9")
    assert sorento_supports_entity(
        ENTITY_AR_OUTSTANDING, contract_version=v210, contract_entities=["ar_outstanding"]
    ) is True
    assert sorento_supports_entity(
        ENTITY_AR_OUTSTANDING, contract_version=v29, contract_entities=["ar_outstanding"]
    ) is False
    assert sorento_supports_entity(
        ENTITY_AR_OUTSTANDING, contract_version=v210, contract_entities=["billing_documents"]
    ) is False


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_opens_at_2_6_with_billing_documents_advertised(entity_type):
    assert sorento_supports_entity(entity_type) is False
    assert sorento_supports_entity(
        entity_type, contract_version=ContractVersion(2, 5), contract_entities=["billing_documents"]
    ) is False
    assert sorento_supports_entity(
        entity_type, contract_version=ContractVersion(2, 6), contract_entities=["billing_documents"]
    ) is True
    assert sorento_supports_entity(
        entity_type, contract_version=ContractVersion.parse("2.10"),
        contract_entities=["billing_documents"],
    ) is True


# ── B. registration ──────────────────────────────────────────────────────────


def test_the_new_families_are_documents_and_disjoint_from_the_old_ones():
    assert set(BILLING_DOCUMENT_ENTITY_TYPES) == set(TABLES)
    for entity_type in ALL_NEW:
        assert entity_type in DOCUMENT_ENTITY_TYPES
        assert is_document_entity(entity_type)
        assert entity_type not in LINKED_DOCUMENT_ENTITY_TYPES
        assert entity_type not in ORDER_DOCUMENT_ENTITY_TYPES
    assert BILLING_DOCUMENT_REF_CODES == CODES


@pytest.mark.parametrize("entity_type", ALL_NEW)
def test_each_new_entity_is_registered_in_every_catalogue(entity_type):
    assert entity_type in ETL_ENTITY_TYPES
    assert entity_type in ENTITY_PROFILES
    assert entity_type in CANONICAL_MODELS
    assert entity_type in DOCUMENT_PRESETS
    assert entity_type in DOCUMENT_PREREQUISITES
    assert entity_type in PUSH_REFUSES_LOGGING_FALLBACK


def test_only_ar_outstanding_has_no_deletions_door():
    assert ENTITY_AR_OUTSTANDING in NO_DELETION_ENTITY_TYPES
    for entity_type in BILLING:
        assert entity_type not in NO_DELETION_ENTITY_TYPES


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_header_ref_is_database_type_code_doc_key(entity_type):
    ref = flat_source_ref(
        {"DocKey": 88213}, database_name=DB, key_columns=["DocKey"], entity_type=entity_type,
    )
    assert ref == f"{DB}:{CODES[entity_type]}:88213"


def test_ar_outstanding_ref_is_database_debtor_auto_key():
    assert AR_OUTSTANDING_REF_MARKER == "debtor"
    ref = flat_source_ref(
        {"DebtorKey": 1234}, database_name=DB, key_columns=["DebtorKey"],
        entity_type=ENTITY_AR_OUTSTANDING,
    )
    assert ref == f"{DB}:debtor:1234"


def test_a_billing_ref_without_a_database_name_is_an_identity_error():
    from modules.autocount.mapping import IdentityError

    with pytest.raises(IdentityError):
        flat_source_ref({"DocKey": 1}, database_name="", key_columns=["DocKey"], entity_type=ENTITY_INVOICE)


# ── B. presets ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_preset_shape(entity_type):
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
    assert preset.from_date == "2023-01-01"
    assert preset.filter_formula is None  # owner ruling: no guessed draft letter
    for column in (
        "DocStatus", "TotalExTax", "Tax", "NetTotal", "CurrencyCode", "CurrencyRate",
        "SalesAgent", "Ref", "Description", "LastModified", "Cancelled", "DebtorCode",
        "DebtorName",
    ):
        assert f"h.{column} AS {column}" in preset.header_query, column
    assert "h.LocalNetTotal - h.LocalTax AS LocalNetExTax" in preset.header_query
    assert "FinalTotal" not in preset.header_query
    for column in (
        "DtlKey", "Seq", "ItemCode", "Description", "UOM", "Qty", "UnitPrice", "DiscountAmt",
        "SubTotalExTax", "TaxCode", "TaxRate", "Tax", "SubTotal", "FromDocType", "FromDocNo",
        "FromDocDtlKey",
    ):
        assert f"d.{column} AS {column}" in preset.line_query, column


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_line_cut_is_the_same_in_all_three_queries(entity_type):
    """REF section 3: keep any line with a non-zero SubTotal, drop pure text
    lines (SubTotal NULL/0 AND Qty NULL). The SAME cut in the header
    aggregate, the line fetch and the sweep, or the fingerprint disagrees."""
    preset = DOCUMENT_PRESETS[entity_type]
    cut = "(d.SubTotal <> 0 OR d.Qty IS NOT NULL)"
    assert cut in preset.header_query
    assert cut in preset.line_query
    assert cut in preset.fingerprint_query
    # A charge line has no ItemCode: the order family's ItemCode cut must NOT apply.
    assert "d.ItemCode IS NOT NULL" not in preset.line_query
    assert "d.ItemCode IS NOT NULL" not in preset.header_query


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_fingerprint_columns(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    for aggregate in (
        "COUNT(*)", "SUM(d.Qty)", "SUM(d.SubTotal)", "SUM(d.Tax)", "MAX(d.DtlKey)",
        "COUNT(d.FromDocDtlKey)",
    ):
        assert aggregate in preset.header_query, aggregate
        assert aggregate in preset.fingerprint_query, aggregate
    transferred = "SUM(d.TransferedQty)"
    if entity_type in (ENTITY_INVOICE, ENTITY_CASH_SALE):
        assert transferred in preset.header_query and transferred in preset.fingerprint_query
    else:
        assert transferred not in preset.header_query and transferred not in preset.fingerprint_query
    # No `LineCount` column: the LineCount guard keys on that exact name and
    # the billing cut differs from the order family's.
    assert "AS LineCount" not in preset.header_query


def test_billing_presets_join_only_the_source_line_tables_they_can_link_to():
    """IV/CS lines come from SO or DO, CN lines from IV only, DN lines have no
    transfer source. Lane SS-BILLING-DO-API (owner ruling 25 Oct): the DO hop
    NEVER joins `DODTL` (the AutoCount admin will not grant it) - the DO
    DocKey is resolved from the DO feed's own ledger instead."""
    joins = {
        ENTITY_INVOICE: {"SODTL"},
        ENTITY_CASH_SALE: {"SODTL"},
        ENTITY_CREDIT_NOTE: {"IVDTL"},
        ENTITY_DEBIT_NOTE: set(),
    }
    for entity_type, expected in joins.items():
        preset = DOCUMENT_PRESETS[entity_type]
        query = preset.line_query
        for table in ("SODTL", "IVDTL"):
            present = f"LEFT JOIN {{database}}.dbo.{table} AS" in query
            assert present == (table in expected), (entity_type, table)
        # No billing query reads DODTL / DO at all, in any of the three queries.
        for text in (preset.header_query, preset.line_query, preset.fingerprint_query):
            assert "DODTL" not in text and ".dbo.DO " not in text, entity_type
        assert "LinkDODocKey" not in query
        assert "LinkDODocKey" not in {row.source_path for row in preset.line}
        # Every join is conditional on the link type, never a blind DtlKey join.
        for table, kind in (("SODTL", "SO"), ("IVDTL", "IV")):
            if table in expected:
                assert f"d.FromDocType = '{kind}'" in query, (entity_type, table)


def test_only_credit_and_debit_notes_select_our_invoice_no():
    for entity_type in BILLING:
        query = DOCUMENT_PRESETS[entity_type].header_query
        has = "h.OurInvoiceNo AS OurInvoiceNo" in query
        assert has == (entity_type in (ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE)), entity_type


def test_billing_presets_never_mix_up_their_tables():
    for entity_type, (header_table, line_table) in TABLES.items():
        preset = DOCUMENT_PRESETS[entity_type]
        for other, (other_header, other_line) in TABLES.items():
            if other == entity_type:
                continue
            assert f".dbo.{other_header} AS h" not in preset.header_query
            assert f"FROM {{database}}.dbo.{other_line} AS d" not in preset.line_query


@pytest.mark.parametrize("entity_type", ALL_NEW)
def test_every_preset_row_targets_a_catalog_field(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    header_ok = accepted_field_names(entity_type)
    line_ok = line_accepted_field_names(entity_type)
    for row in preset.header:
        assert row.canonical_field in header_ok, row
    for row in preset.line:
        assert row.canonical_field in line_ok, row
    assert required_field_names(entity_type) <= {row.canonical_field for row in preset.header}
    assert line_required_field_names(entity_type) <= {row.canonical_field for row in preset.line}


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_catalog(entity_type):
    assert required_field_names(entity_type) == {
        "doc_no", "doc_date", "status", "net_total", "tax_total", "total", "local_net_total",
    }
    assert line_required_field_names(entity_type) == {"source_ref"}
    header = accepted_field_names(entity_type)
    # Minted / fixed, never a mapping target.
    assert not header & {"source_ref", "document_type", "lines"}
    line = line_accepted_field_names(entity_type)
    assert "from_line_ref" not in line  # minted from the link inputs
    for field in ("from_doc_type", "from_doc_no", "from_doc_line_key", "quantity", "net_amount"):
        assert field in line


def test_ar_outstanding_preset_shape():
    preset = DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING]
    assert preset.key_columns == ("DebtorKey",)
    assert preset.watermark_column == "LastModified"
    assert preset.doc_date_column == "LastModified"
    assert "FROM {database}.dbo.Debtor AS c" in preset.header_query
    for table in ("ARInvoice", "ARDN", "ARCN"):
        assert f"{{database}}.dbo.{table} AS" in preset.header_query, table
        assert f"{{database}}.dbo.{table} AS" in preset.line_query, table
        assert f"{{database}}.dbo.{table} AS" in preset.fingerprint_query, table
    # The billing document each AR row belongs to: matched by DocNo + DebtorCode.
    for table in ("IV", "CS", "CN", "DN"):
        assert f"{{database}}.dbo.{table} AS" in preset.line_query, table
    assert f":{LINE_QUERY_DOC_KEY_PARAM}" in preset.line_query
    assert ":from_date" in preset.fingerprint_query
    # A CN is unapplied NetTotal - KnockOffAmt, sent negative.
    assert "-(r.NetTotal - COALESCE(r.KnockOffAmt, 0))" in preset.header_query
    assert "-(r.NetTotal - COALESCE(r.KnockOffAmt, 0))" in preset.line_query
    # AC-32-33 - the read time is never a SQL column (it would move the row
    # hash on every run and re-push every debtor).
    for query in (preset.header_query, preset.line_query, preset.fingerprint_query):
        assert "GETDATE" not in query.upper() and "CURRENT_TIMESTAMP" not in query.upper()
    assert "AS LineCount" not in preset.header_query


def test_ar_outstanding_catalog():
    assert required_field_names(ENTITY_AR_OUTSTANDING) == {"customer_ref", "total_outstanding"}
    assert line_required_field_names(ENTITY_AR_OUTSTANDING) == {
        "ar_doc_type", "ar_doc_key", "outstanding",
    }
    assert "as_of" not in accepted_field_names(ENTITY_AR_OUTSTANDING)  # stamped, never mapped


# ── B. mapping end to end (fake rows) ────────────────────────────────────────


def _engine(entity_type: str, *, link_book: str = BOOK, do_doc_keys=None) -> MappingEngine:
    preset = DOCUMENT_PRESETS[entity_type]
    rows: List[MappingRow] = []
    for scope, fields in ((SCOPE_HEADER, preset.header), (SCOPE_LINE, preset.line)):
        for spec in fields:
            rows.append(MappingRow(
                spec.source_path, spec.canonical_field, spec.transform, scope,
                is_required=spec.required, is_enabled=spec.enabled, formula=spec.formula,
            ))
    return MappingEngine(
        rows, entity_type=entity_type,
        profile=flat_profile(entity_type, list(preset.key_columns)),
        database_name=DB, link_book=link_book, do_doc_keys=do_doc_keys,
    )


def _iv_line(**overrides) -> dict:
    line = {
        "DocKey": 88213, "DtlKey": 1, "Seq": 1, "ItemAutoKey": 10442, "ItemCode": "ABC-1",
        "Description": "Widget", "UOM": "PCS", "Qty": Decimal("10.00000000"),
        "UnitPrice": Decimal("100.00000000"), "DiscountAmt": Decimal("0.00"),
        "SubTotalExTax": Decimal("1000.00"), "TaxCode": "SV-10", "TaxRate": Decimal("10.00"),
        "Tax": Decimal("100.00"), "SubTotal": Decimal("1100.00"),
        "FromDocType": "SO", "FromDocNo": "SO-1", "FromDocDtlKey": 77,
        "LinkSODocKey": 1234, "LinkIVDocKey": None,
    }
    line.update(overrides)
    return line


def _iv_row(**overrides) -> dict:
    row = {
        "DocKey": 88213, "DocNo": "IV-2609/0142", "DocDate": datetime(2026, 9, 26),
        "DocStatus": "F", "DebtorAutoKey": 300, "DebtorCode": "300-X001",
        "DebtorName": "Fake Customer", "SalesAgent": "AGENT1", "CurrencyCode": "MYR",
        "CurrencyRate": Decimal("1.00000000"), "TotalExTax": Decimal("1000.00"),
        "Tax": Decimal("100.00"), "NetTotal": Decimal("1100.00"),
        "LocalNetExTax": Decimal("1000.00"), "Ref": "PROJECT X", "Description": "Sale",
        "Cancelled": "F", "LastModified": datetime(2026, 9, 26, 9, 14, 2, 120000),
        "LineFpCount": 1, "LineFpQty": Decimal("10"), "LineFpSubTotal": Decimal("1100"),
        "LineFpTax": Decimal("100"), "LineFpMaxDtlKey": 1, "LineFpLinked": 1,
        "LineFpTransfered": Decimal("0"),
        "_lines": [_iv_line()],
    }
    row.update(overrides)
    return row


GOLDEN_IV = {
    "source_ref": f"{DB}:IV:88213",
    "document_type": "invoice",
    "doc_no": "IV-2609/0142",
    "doc_date": "2026-09-26",
    "status": "posted",
    "source_modified_at": "2026-09-26T09:14:02.120000+08:00",
    "customer_ref": f"{DB}:300", "customer_code": "300-X001", "customer_name": "Fake Customer",
    "agent_code": "AGENT1",
    "currency_code": "MYR", "currency_rate": 1,
    "net_total": 1000, "tax_total": 100, "total": 1100, "local_net_total": 1000,
    "against_doc_no": None, "against_source_ref": None,
    "ref": "PROJECT X", "description": "Sale",
    "lines": [{
        "source_ref": f"{DB}:IV:88213:1", "line_number": 1,
        "product_ref": f"{DB}:10442", "product_code": "ABC-1", "description": "Widget",
        "uom": "PCS", "quantity": 10, "unit_price": 100, "discount_amount": 0,
        "net_amount": 1000, "tax_code": "SV-10", "tax_rate": 10, "tax_amount": 100,
        "line_total": 1100,
        "from_doc_type": "SO", "from_doc_no": "SO-1", "from_line_ref": f"{DB}:1234:77",
    }],
}


def test_the_invoice_preset_maps_a_fake_row_to_the_exact_contract_record():
    mapped = _engine(ENTITY_INVOICE).map_document(_iv_row())
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert isinstance(mapped.record, CanonicalBillingDocument)
    assert mapped.record.sink_payload() == GOLDEN_IV


def test_the_wire_is_json_numbers_and_every_key_every_time():
    payload = _engine(ENTITY_INVOICE).map_document(_iv_row(Ref=None, Description=None)).record.sink_payload()
    assert set(payload) == HEADER_WIRE_KEYS
    assert set(payload["lines"][0]) == LINE_WIRE_KEYS
    # A push names the whole document: an empty optional is an explicit null.
    assert payload["ref"] is None and payload["description"] is None
    for key in ("net_total", "tax_total", "total", "local_net_total", "currency_rate"):
        assert isinstance(payload[key], (int, float)) and not isinstance(payload[key], bool), key
    # Survives a JSON round trip exactly (no Decimal / datetime leaks).
    assert json.loads(json.dumps(payload)) == payload


def test_a_fractional_amount_stays_exact():
    row = _iv_row(TotalExTax=Decimal("1000.05"), Tax=Decimal("100.01"), NetTotal=Decimal("1100.06"))
    payload = _engine(ENTITY_INVOICE).map_document(row).record.sink_payload()
    assert payload["net_total"] == 1000.05 and payload["total"] == 1100.06


def test_a_cancelled_invoice_is_status_cancelled():
    mapped = _engine(ENTITY_INVOICE).map_document(_iv_row(Cancelled="T"))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["status"] == "cancelled"


def test_a_status_outside_posted_cancelled_is_rejected():
    with pytest.raises(ValueError):
        CanonicalBillingDocument(
            source_ref="x", entity_type=ENTITY_INVOICE, status="open",
        )


@pytest.mark.parametrize("entity_type", BILLING)
def test_document_type_is_fixed_per_entity(entity_type):
    model = CANONICAL_MODELS[entity_type]
    record = model(source_ref=f"{DB}:{CODES[entity_type]}:1")
    assert record.sink_payload()["document_type"] == entity_type


def _do_keys(table: Dict[str, List[int]]):
    """A fake DO-feed-ledger lookup: (book, DO number) -> the delivered
    DocKeys. Only answers for BOOK: the engine must ask with its own book."""
    calls: List[str] = []

    def lookup(book: str, doc_no: str) -> List[int]:
        calls.append(doc_no)
        return list(table.get(doc_no, [])) if book == BOOK else []

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def _do_line(**overrides) -> dict:
    values = dict(
        FromDocType="DO", FromDocNo="DO-2609/0077", FromDocDtlKey=555, LinkSODocKey=None,
    )
    values.update(overrides)
    return _iv_line(**values)


def test_a_do_line_links_to_the_do_feed_book_line_via_the_ledger():
    """Lane SS-BILLING-DO-API - the DO DocKey comes from the DO feed ledger
    (looked up by the line's FromDocNo within the link book), never DODTL."""
    row = _iv_row(_lines=[_do_line()])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=lookup).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["from_line_ref"] == f"{BOOK}:DO:9001:555"
    assert line["from_doc_type"] == "DO" and line["from_doc_no"] == "DO-2609/0077"
    assert lookup.calls == ["DO-2609/0077"]


def test_a_cash_sale_do_line_links_the_same_way():
    row = _iv_row(_lines=[_do_line()])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_CASH_SALE, link_book=BOOK, do_doc_keys=lookup).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["lines"][0]["from_line_ref"] == f"{BOOK}:DO:9001:555"


def test_a_stale_sql_link_column_is_never_trusted_over_the_ledger():
    """A task still on the pre-lane lineQuery may hand a LinkDODocKey; the
    ledger is the only authority, so a disagreeing column is ignored."""
    row = _iv_row(_lines=[_do_line(LinkDODocKey=1)])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=lookup).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["lines"][0]["from_line_ref"] == f"{BOOK}:DO:9001:555"


def test_a_do_line_without_a_do_feed_book_is_a_named_error_never_unlinked():
    """Owner ruling 20 Oct: exact links only, fail loudly. A DO-sourced line
    on a company with no doc-feed book must not be pushed with a null ref."""
    row = _iv_row(_lines=[_do_line()])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_INVOICE, link_book="", do_doc_keys=lookup).map_document(row)
    assert not mapped.ok
    assert any("book" in e.message().lower() for e in mapped.errors), [e.message() for e in mapped.errors]


@pytest.mark.parametrize("table,needle", [
    ({}, "no delivery order"),  # the DO feed never delivered it
    ({"DO-2609/0077": [9001, 9002]}, "2 delivery orders"),  # ambiguous: never guess
])
def test_a_do_line_the_ledger_cannot_pin_to_one_do_is_a_named_error(table, needle):
    row = _iv_row(_lines=[_do_line()])
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=_do_keys(table)).map_document(row)
    assert not mapped.ok
    messages = [e.message() for e in mapped.errors]
    assert any(needle in m.lower() for m in messages), messages
    assert any(e.field == "from_line_ref" for e in mapped.errors)


@pytest.mark.parametrize("overrides", [{"FromDocNo": None}, {"FromDocNo": "   "}])
def test_a_do_line_with_no_do_number_is_a_named_error(overrides):
    row = _iv_row(_lines=[_do_line(**overrides)])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=lookup).map_document(row)
    assert not mapped.ok
    assert lookup.calls == []


def test_a_do_line_with_no_ledger_lookup_wired_fails_closed():
    """An engine built without the lookup (a caller that forgot it) must
    fail the DO line, never push it unlinked."""
    row = _iv_row(_lines=[_do_line()])
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK).map_document(row)
    assert not mapped.ok
    assert any(e.field == "from_line_ref" for e in mapped.errors)


def test_a_do_line_with_no_source_line_key_sends_type_and_number_only():
    """Unchanged rule: a NULL FromDocDtlKey cannot be linked - no lookup."""
    row = _iv_row(_lines=[_do_line(FromDocDtlKey=None)])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    mapped = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=lookup).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["lines"][0]["from_line_ref"] is None
    assert lookup.calls == []


def test_the_ledger_lookup_is_asked_once_per_do_number():
    row = _iv_row(_lines=[
        _do_line(DtlKey=1, FromDocDtlKey=555),
        _do_line(DtlKey=2, FromDocDtlKey=556),
    ])
    lookup = _do_keys({"DO-2609/0077": [9001]})
    engine = _engine(ENTITY_INVOICE, link_book=BOOK, do_doc_keys=lookup)
    mapped = engine.map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    refs = [line["from_line_ref"] for line in mapped.record.sink_payload()["lines"]]
    assert refs == [f"{BOOK}:DO:9001:555", f"{BOOK}:DO:9001:556"]
    engine.map_document(row)
    assert lookup.calls == ["DO-2609/0077"]


def test_a_credit_note_line_links_to_its_invoice_line():
    row = _iv_row(
        DocKey=4410, DocNo="CN-1", OurInvoiceNo=" IV-2609/0142 , IV-2609/0143",
        _lines=[_iv_line(
            DocKey=4410, DtlKey=3, FromDocType="IV", FromDocNo="IV-2609/0142", FromDocDtlKey=1,
            LinkSODocKey=None, LinkIVDocKey=88213, Qty=Decimal("-1"),
        )],
    )
    mapped = _engine(ENTITY_CREDIT_NOTE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    payload = mapped.record.sink_payload()
    assert payload["source_ref"] == f"{DB}:CN:4410"
    assert payload["document_type"] == "credit_note"
    assert payload["against_doc_no"] == "IV-2609/0142"  # first entry of the comma list
    assert payload["against_source_ref"] is None
    line = payload["lines"][0]
    assert line["source_ref"] == f"{DB}:CN:4410:3"
    assert line["from_line_ref"] == f"{DB}:IV:88213:1"
    assert line["quantity"] == -1  # a CN line may be negative; the CRM checks IV/CS only


@pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("  ", None), (" , IV-9", "IV-9")])
def test_against_doc_no_is_the_first_non_blank_entry(raw, expected):
    row = _iv_row(DocKey=1, DocNo="DN-1", OurInvoiceNo=raw, _lines=[_iv_line(
        DocKey=1, FromDocType=None, FromDocNo=None, FromDocDtlKey=None, LinkSODocKey=None,
    )])
    mapped = _engine(ENTITY_DEBIT_NOTE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["against_doc_no"] == expected


@pytest.mark.parametrize("overrides", [
    {"FromDocDtlKey": None},  # NULL key (XSDTL-style): number only
    {"FromDocType": "QT", "FromDocNo": "QT-1", "LinkSODocKey": None},  # a quotation: no ref
    {"LinkSODocKey": None},  # the SO line is not found in SODTL: no guess
])
def test_an_unlinkable_line_keeps_type_and_number_and_sends_no_ref(overrides):
    row = _iv_row(_lines=[_iv_line(**overrides)])
    mapped = _engine(ENTITY_INVOICE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["from_line_ref"] is None
    assert line["from_doc_type"] == overrides.get("FromDocType", "SO")


def test_a_charge_line_without_an_item_is_kept_with_no_product():
    row = _iv_row(_lines=[_iv_line(
        DtlKey=9, ItemAutoKey=None, ItemCode=None, Description="Delivery charge", Qty=None,
        UnitPrice=None, SubTotalExTax=Decimal("50"), Tax=Decimal("5"), SubTotal=Decimal("55"),
        FromDocType=None, FromDocNo=None, FromDocDtlKey=None, LinkSODocKey=None,
    )])
    mapped = _engine(ENTITY_INVOICE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["product_ref"] is None and line["product_code"] is None
    assert line["quantity"] is None and line["line_total"] == 55


def test_link_inputs_never_reach_the_wire():
    payload = _engine(ENTITY_INVOICE).map_document(_iv_row()).record.sink_payload()
    line = payload["lines"][0]
    for key in ("link_so_doc_key", "link_do_doc_key", "link_iv_doc_key", "from_doc_line_key"):
        assert key not in line


def test_the_staged_json_round_trip_keeps_the_wire():
    record = _engine(ENTITY_INVOICE).map_document(_iv_row()).record
    rehydrated = CANONICAL_MODELS[ENTITY_INVOICE](**json.loads(json.dumps(record.model_dump(mode="json"))))
    assert rehydrated.sink_payload() == GOLDEN_IV


def test_a_missing_required_total_is_a_named_mapping_error():
    mapped = _engine(ENTITY_INVOICE).map_document(_iv_row(LocalNetExTax=None))
    assert not mapped.ok
    assert any(e.field == "local_net_total" for e in mapped.errors)


# ── C. AR outstanding mapping ────────────────────────────────────────────────


def _ar_row(**overrides) -> dict:
    row = {
        "DebtorKey": 1234, "DebtorCode": "300-X001",
        "TotalOutstanding": Decimal("15230.40"), "OpenCount": 2,
        "LastModified": datetime(2026, 10, 20, 8, 0, 0),
        "_lines": [
            {"DocType": "IV", "BillingDocKey": 88213, "Outstanding": Decimal("1100.00"),
             "DueDate": datetime(2026, 11, 25)},
            {"DocType": "CN", "BillingDocKey": 4410, "Outstanding": Decimal("-200.00"),
             "DueDate": None},
        ],
    }
    row.update(overrides)
    return row


def test_the_ar_preset_maps_a_fake_debtor_to_the_exact_contract_record():
    before = datetime.now(timezone.utc)
    mapped = _engine(ENTITY_AR_OUTSTANDING).map_document(_ar_row())
    after = datetime.now(timezone.utc)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert isinstance(mapped.record, CanonicalArOutstanding)
    payload = mapped.record.sink_payload()
    as_of = payload.pop("as_of")
    assert payload == {
        "source_ref": f"{DB}:debtor:1234",
        "customer_ref": f"{DB}:1234",
        "customer_code": "300-X001",
        "total_outstanding": 15230.4,
        "documents": [
            {"source_ref": f"{DB}:IV:88213", "outstanding": 1100, "due_date": "2026-11-25"},
            {"source_ref": f"{DB}:CN:4410", "outstanding": -200, "due_date": None},
        ],
    }
    assert as_of.endswith("+08:00")
    stamped = datetime.fromisoformat(as_of)
    assert before - timedelta(seconds=1) <= stamped <= after + timedelta(seconds=1)


def test_a_paid_off_debtor_sends_zero_and_an_empty_list():
    mapped = _engine(ENTITY_AR_OUTSTANDING).map_document(
        _ar_row(TotalOutstanding=Decimal("0.00"), OpenCount=0, _lines=[])
    )
    assert mapped.ok, [e.message() for e in mapped.errors]
    payload = mapped.record.sink_payload()
    assert payload["total_outstanding"] == 0
    assert payload["documents"] == []


def test_an_ar_line_with_an_unknown_doc_type_is_a_named_error():
    row = _ar_row(_lines=[{"DocType": "RI", "BillingDocKey": 1, "Outstanding": Decimal("1"), "DueDate": None}])
    mapped = _engine(ENTITY_AR_OUTSTANDING).map_document(row)
    assert not mapped.ok


def test_as_of_survives_the_staged_round_trip_and_is_not_restamped():
    record = _engine(ENTITY_AR_OUTSTANDING).map_document(_ar_row()).record
    stored = json.loads(json.dumps(record.model_dump(mode="json")))
    rehydrated = CANONICAL_MODELS[ENTITY_AR_OUTSTANDING](**stored)
    assert rehydrated.sink_payload() == record.sink_payload()


def test_ar_lines_are_not_prefixed_with_the_debtor_ref():
    assert ENTITY_PROFILES[ENTITY_AR_OUTSTANDING].line_ref_prefix is False
    for entity_type in BILLING:
        assert ENTITY_PROFILES[entity_type].line_ref_prefix is True


# ── B/C. sink ────────────────────────────────────────────────────────────────


def _ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    records = [
        {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "id"}
        for r in body.get("records", [])
    ]
    return httpx.Response(200, json={
        "summary": {"total": len(records), "created": len(records), "updated": 0,
                    "failed": 0, "retryable": 0},
        "records": records,
    })


@pytest.mark.parametrize("entity_type", BILLING)
def test_billing_posts_to_the_one_door_with_no_book(entity_type):
    requests: List[httpx.Request] = []

    def handle(request):
        requests.append(request)
        return _ok(request)

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=entity_type,
                       company_code="ABC", transport=httpx.MockTransport(handle))
    record = CANONICAL_MODELS[entity_type](source_ref=f"{DB}:{CODES[entity_type]}:1", doc_no="D-1")
    [result] = sink.write_batch([record], request_id="t")
    assert requests[0].url.path == "/api/v1/external/ingest/billing_documents"
    body = json.loads(requests[0].content)
    assert set(body) == {"companyCode", "records"}
    assert body["records"][0]["document_type"] == entity_type
    assert result.delivered is True


def test_billing_deletions_post_source_refs_to_the_billing_door():
    requests: List[httpx.Request] = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "summary": {"total": 1, "deleted": 1},
            "records": [{"source_ref": r, "outcome": "deleted"} for r in body["source_refs"]],
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_CREDIT_NOTE,
                       company_code="ABC", transport=httpx.MockTransport(handle))
    sink.delete_batch([f"{DB}:CN:4410"])
    assert requests[0].url.path == "/api/v1/external/ingest/billing_documents/deletions"
    assert json.loads(requests[0].content) == {"companyCode": "ABC", "source_refs": [f"{DB}:CN:4410"]}


def test_ar_outstanding_posts_to_its_own_door():
    requests: List[httpx.Request] = []

    def handle(request):
        requests.append(request)
        return _ok(request)

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_AR_OUTSTANDING,
                       company_code="ABC", transport=httpx.MockTransport(handle))
    record = _engine(ENTITY_AR_OUTSTANDING).map_document(_ar_row()).record
    sink.write_batch([record], request_id="t")
    assert requests[0].url.path == "/api/v1/external/ingest/ar_outstanding"
    body = json.loads(requests[0].content)
    assert set(body) == {"companyCode", "records"}
    assert set(body["records"][0]) == {
        "source_ref", "customer_ref", "customer_code", "as_of", "total_outstanding", "documents",
    }


def _staged(db, company_id, entity_type):
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
        payload_json={"companyId": company_id, "entityType": entity_type},
    )
    db.add(job)
    db.commit()
    if entity_type == ENTITY_AR_OUTSTANDING:
        record = _engine(entity_type).map_document(_ar_row()).record
    else:
        record = CANONICAL_MODELS[entity_type](source_ref=f"{DB}:{CODES[entity_type]}:1", doc_no="D-1")
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=entity_type,
        job_id=job.id, source_ref=record.source_ref, doc_no="D-1",
        raw_json={"DocKey": 1}, canonical_json=record.model_dump(mode="json"), status=STAGED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, job


@pytest.mark.parametrize("entity_type,version,entities", [
    (ENTITY_INVOICE, "2.5", ["billing_documents"]),
    (ENTITY_CREDIT_NOTE, "2.10", ["sales_orders"]),
    (ENTITY_AR_OUTSTANDING, "2.9", ["ar_outstanding", "billing_documents"]),
    (ENTITY_AR_OUTSTANDING, "2.10", ["billing_documents"]),
])
def test_auto_push_refuses_a_shut_gate_and_leaves_rows_staged(
    monkeypatch, _stock_gate_rig, entity_type, version, entities,
):
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=ContractVersion.parse(version), entities=entities),
    )
    db, company = _stock_gate_rig
    row, job = _staged(db, company.id, entity_type)
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, entity_type, job_id=job.id)
    assert summary.get("errorCode") == "CONTRACT_GATE", summary
    db.refresh(row)
    assert row.status == STAGED


@pytest.mark.parametrize("entity_type", ALL_NEW)
def test_sink_for_company_opens_on_the_live_2_10_contract(monkeypatch, _stock_gate_rig, entity_type):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(
            version=ContractVersion.parse("2.10"), entities=["billing_documents", "ar_outstanding"],
        ),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, entity_type)
    assert isinstance(sink, SorentoSink)
    assert sink.book is None  # neither door takes a book


@pytest.mark.parametrize("entity_type", ALL_NEW)
def test_sink_for_company_falls_back_to_logging_on_an_old_contract(monkeypatch, _stock_gate_rig, entity_type):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=ContractVersion(2, 5), entities=["billing_documents"]),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, entity_type)
    assert sink.name == SINK_LOGGING


def test_the_contract_banner_knows_each_requirement():
    from modules.autocount.services.company_service import CompanyService

    for entity_type in BILLING:
        assert CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[entity_type] == ContractVersion(2, 6)
    assert CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[ENTITY_AR_OUTSTANDING] == ContractVersion(2, 10)


def test_the_link_book_is_the_do_feed_book_for_invoices_and_cash_sales(_stock_gate_rig):
    from modules.autocount.http_source.book import billing_link_book, identity_scope
    from modules.autocount.models import AcDocFeed

    db, company = _stock_gate_rig
    assert billing_link_book(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE) == ""
    db.add(AcDocFeed(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, feed="delivery_orders", book=BOOK))
    db.commit()
    assert billing_link_book(db, DEFAULT_TENANT_ID, company, ENTITY_INVOICE) == BOOK
    assert billing_link_book(db, DEFAULT_TENANT_ID, company, ENTITY_CASH_SALE) == BOOK
    # Only IV/CS lines can come from a DO.
    assert billing_link_book(db, DEFAULT_TENANT_ID, company, ENTITY_CREDIT_NOTE) == ""
    # The header identity stays the database name, never the book.
    for entity_type in ALL_NEW:
        assert identity_scope(db, DEFAULT_TENANT_ID, company, entity_type, None) == company.database_name


# ── D11 push order ───────────────────────────────────────────────────────────


def test_the_sweep_enqueues_invoices_and_cash_sales_before_notes():
    from modules.autocount.scheduler import sweep_order_key

    entities = [ENTITY_DEBIT_NOTE, ENTITY_CREDIT_NOTE, "customer", ENTITY_CASH_SALE, ENTITY_INVOICE]
    ordered = sorted(entities, key=sweep_order_key)
    assert ordered.index(ENTITY_INVOICE) < ordered.index(ENTITY_CREDIT_NOTE)
    assert ordered.index(ENTITY_CASH_SALE) < ordered.index(ENTITY_DEBIT_NOTE)
    assert ordered.index(ENTITY_INVOICE) < ordered.index(ENTITY_DEBIT_NOTE)
    assert ordered.index(ENTITY_CASH_SALE) < ordered.index(ENTITY_CREDIT_NOTE)


# ── review round 1 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", sorted(DOCUMENT_PRESETS))
def test_every_fingerprint_query_keys_its_rows_on_doc_key(entity_type):
    """Review B1: `SqlDbSource.fetch_fingerprints` reads the raw key from a
    column aliased exactly `DocKey`; any other alias makes the sweep a silent
    no-op (the AR sweep once used `DebtorKey`)."""
    import re

    query = DOCUMENT_PRESETS[entity_type].fingerprint_query
    match = re.match(r"SELECT \S+ AS (\w+)", query)
    assert match and match.group(1) == "DocKey", query[:80]


def test_the_ar_fingerprint_sweep_finds_a_debtor(monkeypatch):
    """B1 end to end through `fetch_fingerprints`: a row shaped like the AR
    sweep's own output yields that debtor's ref."""
    import contextlib
    import re

    from modules.autocount.sql_source import source as source_module
    from modules.autocount.sql_source.source import SqlDbSource

    query = DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING].fingerprint_query
    aliases = re.findall(r" AS (\w+)(?:,| FROM)", query.split(" FROM ", 1)[0] + " FROM")
    row = dict(zip(aliases, [1234, Decimal("10"), 1, datetime(2026, 10, 1)]))

    class _Row:
        _mapping = row

    class _Conn:
        def execute(self, *_a, **_k):
            class _Result:
                def fetchall(self_inner):
                    return [_Row()]
            return _Result()

    monkeypatch.setattr(
        source_module, "open_readonly", lambda *a, **k: contextlib.nullcontext(_Conn()),
    )
    source = SqlDbSource.__new__(SqlDbSource)
    source._fingerprint_query_exec = query
    source._engine = None
    source.timeout_s = 1
    source._secrets = []
    source.from_date = date(2000, 1, 1)
    source.key_columns = ["DebtorKey"]
    source.entity_type = ENTITY_AR_OUTSTANDING
    source._identity_scope_cache = DB
    out = source.fetch_fingerprints()
    assert list(out) == [f"{DB}:debtor:1234"]


def test_the_ar_match_is_one_to_one_both_ways():
    """Review S4: an AR row is listed only when it matches exactly one billing
    document AND no other row of its own AR table shares its DocNo + debtor
    (else two items mint one ref and the debtor's snapshot is rejected)."""
    query = DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING].line_query
    assert query.count("m.ArHits = 1") == 3
    for table in ("ARInvoice", "ARDN", "ARCN"):
        assert f"FROM {{database}}.dbo.{table} AS a2" in query, table
    for hits in ("m.IvHits + m.CsHits = 1", "m.DnHits = 1", "m.CnHits = 1"):
        assert hits in query


def test_a_missing_knock_off_or_last_modified_never_drops_an_ar_row():
    """Review N3/N4: a NULL `KnockOffAmt` is 0 and a NULL `LastModified` is the
    floor, so neither silently removes an item from the total."""
    preset = DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING]
    assert "COALESCE(r.KnockOffAmt, 0)" in preset.header_query
    assert "COALESCE(r.KnockOffAmt, 0)" in preset.line_query
    for alias in ("i", "n", "r"):
        assert f"COALESCE({alias}.LastModified," in preset.header_query, alias


def test_an_invoice_without_a_delivery_orders_book_warns_up_front():
    """Review S2 (foolproof-UI): IV/CS lines from a DO need the DO feed's book."""
    from modules.autocount.doc_feed.constants import FEED_DELIVERY_ORDERS
    from types import SimpleNamespace

    from modules.autocount.models import ETL_STATUS_ACTIVE
    from modules.autocount.services.company_service import document_prerequisites

    states = [
        SimpleNamespace(entity_type=e, etl_status=ETL_STATUS_ACTIVE, enabled=True)
        for e in ("customer", "product", ENTITY_INVOICE, ENTITY_CREDIT_NOTE)
    ]
    out = {p.entity_type: p for p in document_prerequisites(states, has_delivery_order_book=False)}
    assert FEED_DELIVERY_ORDERS in out[ENTITY_INVOICE].inactive
    assert FEED_DELIVERY_ORDERS not in out[ENTITY_CREDIT_NOTE].inactive
    out = {p.entity_type: p for p in document_prerequisites(states)}
    assert FEED_DELIVERY_ORDERS not in out[ENTITY_INVOICE].inactive


def test_the_sweep_fires_notes_after_invoices(session_factory, monkeypatch):
    """Review S1: the real `sweep_etl_tasks` enqueues IV/CS before CN/DN, even
    when the notes' rows come first."""
    from modules.autocount import scheduler as scheduler_module
    from modules.autocount.models import ETL_STATUS_ACTIVE, SOURCE_IMPL_SQL_DB, AcEntityConfig
    from tests.test_autocount_scheduler import NOW, _company

    db = session_factory()
    try:
        company = _company(db)
        for entity_type in (ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE, ENTITY_INVOICE, ENTITY_CASH_SALE):
            db.add(AcEntityConfig(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
                source_impl=SOURCE_IMPL_SQL_DB, etl_status=ETL_STATUS_ACTIVE,
                source_config={"incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00"},
                next_incremental_at=NOW - timedelta(minutes=1),
            ))
        db.commit()
        fired: List[str] = []
        monkeypatch.setattr(
            scheduler_module, "_sweep_one",
            lambda db_, config, now: fired.append(config.entity_type) or "skipped",
        )
        scheduler_module.sweep_etl_tasks(db, now=NOW)
        billing = [e for e in fired if e in BILLING]
        assert set(billing) == set(BILLING)
        last_doc = max(billing.index(ENTITY_INVOICE), billing.index(ENTITY_CASH_SALE))
        first_note = min(billing.index(ENTITY_CREDIT_NOTE), billing.index(ENTITY_DEBIT_NOTE))
        assert last_doc < first_note, billing
    finally:
        db.close()


def test_the_company_detail_endpoint_warns_an_invoice_without_a_delivery_orders_book(
    client, session_factory,
):
    """Review round 2 SF2: the DO-book prerequisite is wired through the real
    detail route. A GRN feed book does not count; the DO feed's book clears it."""
    from modules.autocount.models import AcDocFeed, AcEntityConfig
    from tests.test_autocount_db_company import _auth
    from tests.test_autocount_documents import _company

    db = session_factory()
    company = _company(db)
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_INVOICE, source_impl="sql_db",
    ))
    db.commit()
    headers = _auth(client)

    def invoice_line():
        body = client.get(f"/autocount/companies/{company.id}", headers=headers).json()
        return next(
            p for p in body["company"]["documentPrerequisites"]
            if p["entityType"] == ENTITY_INVOICE
        )

    try:
        assert "delivery_orders" in invoice_line()["inactive"]
        db.add(AcDocFeed(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, feed="goods_receive_notes", book="grnbook",
        ))
        db.commit()
        assert "delivery_orders" in invoice_line()["inactive"]
        db.add(AcDocFeed(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, feed="delivery_orders", book=BOOK,
        ))
        db.commit()
        assert "delivery_orders" not in invoice_line()["inactive"]
    finally:
        db.close()
