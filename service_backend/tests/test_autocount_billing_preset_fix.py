"""Plan 35 (lane SS-BILLING-PRESET-FIX) - the billing presets against the
real AutoCount schema (scout AC-BILLING-ACCESS-CHECK, 27 Oct, read-only
queries on the FXView grant).

* F1 drafts (`DocStatus='D'`) never push as `posted`; `E` is kept.
* F2 `CS` has no `DocStatus` column.
* F3 `DNDTL` has no `FromDocType` / `FromDocNo` / `FromDocDtlKey`.
* F4 cancelled ARDN / ARCN rows never reach the AR total or lines.
* F5 the DO hop is the PR #127 `DODTL` join again (the grant exists): a DO
  line with a source line key links exactly; a line with only `FromDocNo`
  sends the DO header link (type + number) and no line ref; never a guess.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List

import pytest

from modules.autocount.canonical.documents import (
    ENTITY_AR_OUTSTANDING,
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
)
from modules.autocount.formula import evaluate_row_filter
from modules.autocount.mapping import (
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    flat_profile,
)
from modules.autocount.presets import DOCUMENT_PRESETS

from tests.test_autocount_billing_feed import _iv_line, _iv_row

DB = "FAKE_DB"
BOOK = "fakebook"
BILLING = (ENTITY_INVOICE, ENTITY_CASH_SALE, ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE)
DODTL_JOIN = (
    "LEFT JOIN {database}.dbo.DODTL AS dd ON d.FromDocType = 'DO' "
    "AND dd.DtlKey = d.FromDocDtlKey"
)


# ── F1 drafts ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", BILLING)
@pytest.mark.parametrize("status,kept", [
    ("A", True),   # posted
    ("V", True),   # void: pushed as cancelled by the Cancelled flag
    ("E", True),   # 5 IV in 2025, meaning asked of the owner: kept for now
    (None, True),  # CS has no DocStatus column (F2)
    ("D", False),  # draft: never pushed as posted
])
def test_billing_filter_drops_drafts_only(entity_type, status, kept):
    formula = DOCUMENT_PRESETS[entity_type].filter_formula
    assert formula, entity_type
    assert evaluate_row_filter(formula, {"DocStatus": status, "DocNo": "X-1"}) is kept


def test_the_ar_sweep_has_no_draft_filter():
    """AR rows carry no DocStatus; a draft never has an AR row (scout)."""
    assert DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING].filter_formula is None


# ── F2 CS has no DocStatus ───────────────────────────────────────────────────


def test_cash_sale_selects_a_null_doc_status():
    query = DOCUMENT_PRESETS[ENTITY_CASH_SALE].header_query
    assert "NULL AS DocStatus" in query
    assert "h.DocStatus" not in query


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE])
def test_the_other_billing_headers_still_read_doc_status(entity_type):
    assert "h.DocStatus AS DocStatus" in DOCUMENT_PRESETS[entity_type].header_query


# ── F3 DNDTL has no FromDoc* columns ─────────────────────────────────────────


def test_debit_note_never_reads_a_from_doc_column():
    preset = DOCUMENT_PRESETS[ENTITY_DEBIT_NOTE]
    for text in (preset.header_query, preset.line_query, preset.fingerprint_query):
        assert "FromDoc" not in text
        assert "LineFpLinked" not in text
    targets = {field.canonical_field for field in preset.line}
    assert not targets & {"from_doc_type", "from_doc_no", "from_doc_line_key"}
    sources = {field.source_path for field in preset.line}
    assert not {s for s in sources if s.startswith("FromDoc")}


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE, ENTITY_CREDIT_NOTE])
def test_the_linked_billing_documents_keep_the_link_fingerprint(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    assert "COUNT(d.FromDocDtlKey) AS LineFpLinked" in preset.header_query
    assert "COUNT(d.FromDocDtlKey) AS LineFpLinked" in preset.fingerprint_query
    for column in ("FromDocType", "FromDocNo", "FromDocDtlKey"):
        assert f"d.{column} AS {column}" in preset.line_query


# ── F4 cancelled ARDN / ARCN ─────────────────────────────────────────────────


@pytest.mark.parametrize("query_name", ["header_query", "line_query", "fingerprint_query"])
def test_ar_never_counts_a_cancelled_debit_or_credit_note(query_name):
    query = getattr(DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING], query_name)
    assert "COALESCE(i.Cancelled, 'F') <> 'T'" in query
    assert "COALESCE(n.Cancelled, 'F') <> 'T'" in query
    assert "COALESCE(r.Cancelled, 'F') <> 'T'" in query


def test_the_ar_cancel_filter_sits_on_its_own_table():
    """Each guard filters the SELECT that reads that table (a misplaced
    alias would be a SQL error or a no-op)."""
    for query_name in ("header_query", "line_query"):
        query = getattr(DOCUMENT_PRESETS[ENTITY_AR_OUTSTANDING], query_name)
        dn = query.index("FROM {database}.dbo.ARDN AS n")
        cn = query.index("FROM {database}.dbo.ARCN AS r")
        assert dn < query.index("COALESCE(n.Cancelled, 'F') <> 'T'") < cn
        assert cn < query.index("COALESCE(r.Cancelled, 'F') <> 'T'")


# ── F5 DO link: the DODTL join, exact links only ─────────────────────────────


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_invoice_and_cash_sale_join_dodtl_for_the_do_line(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    assert DODTL_JOIN in preset.line_query
    assert "dd.DocKey AS LinkDODocKey" in preset.line_query
    [row] = [field for field in preset.line if field.source_path == "LinkDODocKey"]
    assert (row.canonical_field, row.transform) == ("link_do_doc_key", "int")
    # The DODTL hop is a line-fetch join only: the header and the sweep never read it.
    assert "DODTL" not in preset.header_query and "DODTL" not in preset.fingerprint_query


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_the_restored_line_query_is_the_plan_32_text_byte_for_byte(entity_type):
    """The restore is the PR #127 join exactly, so a task the 0032 pass never
    touched (a customised query) and a fresh task read the same SQL."""
    from modules.autocount.backfill import _OLD_BILLING_DO_LINE_QUERIES

    assert DOCUMENT_PRESETS[entity_type].line_query == _OLD_BILLING_DO_LINE_QUERIES[entity_type]


@pytest.mark.parametrize("entity_type", [ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE])
def test_notes_never_join_dodtl(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    assert "DODTL" not in preset.line_query
    assert "LinkDODocKey" not in {field.source_path for field in preset.line}


def _engine(entity_type: str, *, link_book: str = BOOK) -> MappingEngine:
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
        database_name=DB, link_book=link_book,
    )


def _do_line(**overrides) -> dict:
    values = dict(
        FromDocType="DO", FromDocNo="DO-2609/0077", FromDocDtlKey=555,
        LinkSODocKey=None, LinkDODocKey=9001,
    )
    values.update(overrides)
    return _iv_line(**values)


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_a_keyed_do_line_links_to_its_do_line_through_dodtl(entity_type):
    """2023-24 lines carry FromDocDtlKey: DODTL names the DO DocKey."""
    mapped = _engine(entity_type).map_document(_iv_row(_lines=[_do_line()]))
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["from_line_ref"] == f"{BOOK}:DO:9001:555"
    assert (line["from_doc_type"], line["from_doc_no"]) == ("DO", "DO-2609/0077")


def test_a_do_line_with_only_a_do_number_gets_the_do_header_link_and_no_line_ref():
    """2025-26 lines: FromDocDtlKey is NULL, FromDocNo names the DO. The
    document pushes with type + number (the DO header link) and no line ref."""
    row = _iv_row(_lines=[_do_line(FromDocDtlKey=None, LinkDODocKey=None)])
    mapped = _engine(ENTITY_INVOICE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["from_line_ref"] is None
    assert (line["from_doc_type"], line["from_doc_no"]) == ("DO", "DO-2609/0077")


def test_a_keyed_do_line_dodtl_cannot_resolve_is_never_guessed():
    """A key DODTL does not hold (7 of 177,443 in the scout) sends no ref,
    exactly like an unresolved SO line - never a ref built from the DO number."""
    row = _iv_row(_lines=[_do_line(LinkDODocKey=None)])
    mapped = _engine(ENTITY_INVOICE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    line = mapped.record.sink_payload()["lines"][0]
    assert line["from_line_ref"] is None
    assert line["from_doc_no"] == "DO-2609/0077"


def test_a_keyed_do_line_without_a_do_feed_book_is_a_named_error():
    """Owner ruling 20 Oct: exact links only. A resolved DO line on a company
    with no doc-feed book cannot be addressed, so the document fails."""
    mapped = _engine(ENTITY_INVOICE, link_book="").map_document(_iv_row(_lines=[_do_line()]))
    assert not mapped.ok
    errors = [e for e in mapped.errors if e.field == "from_line_ref"]
    assert errors and "book" in errors[0].message().lower()


def test_a_do_number_only_line_needs_no_book():
    row = _iv_row(_lines=[_do_line(FromDocDtlKey=None, LinkDODocKey=None)])
    mapped = _engine(ENTITY_INVOICE, link_book="").map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]


def test_the_engine_takes_no_ledger_lookup():
    """The PR #130 DO-feed-ledger lookup is gone: DODTL is the only source of
    the DO DocKey."""
    with pytest.raises(TypeError):
        MappingEngine(
            [], entity_type=ENTITY_INVOICE,
            profile=flat_profile(ENTITY_INVOICE, ["DocKey"]),
            database_name=DB, link_book=BOOK, do_doc_keys=lambda book, doc_no: [],
        )


def test_a_mixed_invoice_links_each_line_on_its_own_terms():
    row = _iv_row(
        NetTotal=Decimal("3300.00"), TotalExTax=Decimal("3000.00"), Tax=Decimal("300.00"),
        LocalNetExTax=Decimal("3000.00"),
        _lines=[
            _iv_line(DtlKey=1),                                           # SO line
            _do_line(DtlKey=2),                                           # keyed DO line
            _do_line(DtlKey=3, FromDocDtlKey=None, LinkDODocKey=None),    # DO number only
        ],
    )
    mapped = _engine(ENTITY_INVOICE).map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    refs = [line["from_line_ref"] for line in mapped.record.sink_payload()["lines"]]
    assert refs == [f"{DB}:1234:77", f"{BOOK}:DO:9001:555", None]
