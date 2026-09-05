"""Unit tests for the PURE transform functions in
`scripts/seed_autocount_shape_source.py` (plan sprint-5/02 S4 prep, dev
fixture rig). The real oracle xlsx paths live OUTSIDE the repo
(`~/Desktop/...xlsx`, a sibling `sorento-crm` checkout) so this suite never
touches xlsx or a real database - it feeds inline sample rows shaped exactly
like the two oracle books' real headers into the row->table-dict builders,
the netting/outstanding transform, and the deterministic SPO-clone /
open-PO helpers.
"""
from __future__ import annotations

from datetime import date, datetime

from scripts.seed_autocount_shape_source import (
    _creditor_code,
    _excel_date,
    _num,
    _transfered_qty,
    assign_keys,
    build_po_rows,
    build_so_rows,
    clone_spo_docs,
    derive_creditors,
    derive_debtors,
    derive_items,
    derive_locations,
    derive_sales_agents,
    mark_po_rows_open,
)


# ---------------------------------------------------------------------------
# scalar helpers
# ---------------------------------------------------------------------------


def test_num_blank_stays_none_never_zero():
    assert _num(None) is None
    assert _num("") is None
    assert _num("not-a-number") is None
    assert _num(0) == 0.0
    assert _num("12.5") == 12.5


def test_transfered_qty_nets_against_remaining_when_present():
    # AC-adjacent netting rule: TransferedQty = Qty - Remaining (Remaining
    # if present else 0) - the rig's OWN canonical figure, not whatever the
    # oracle's "Transfered Qty" column says.
    assert _transfered_qty(40, 39) == 1
    assert _transfered_qty(10, None) == 10
    assert _transfered_qty(None, None) == 0


def test_excel_date_accepts_serial_and_real_datetime():
    # SO oracle: raw Excel serial (General format, no date type).
    assert _excel_date(44995) == date(2023, 3, 10)
    # PO/SPO oracle: already a real datetime cell.
    assert _excel_date(datetime(2023, 1, 3)) == date(2023, 1, 3)
    assert _excel_date(date(2023, 1, 3)) == date(2023, 1, 3)
    assert _excel_date(None) is None
    assert _excel_date("") is None


def test_creditor_code_is_deterministic_and_stable():
    code1 = _creditor_code("XIAMEN TAIYANG TECHNOLOGY CO.,LTD")
    code2 = _creditor_code("XIAMEN TAIYANG TECHNOLOGY CO.,LTD")
    assert code1 == code2
    assert code1.startswith("CR-")
    # Different names -> different (still deterministic) codes.
    assert _creditor_code("SOME OTHER SUPPLIER") != code1


# ---------------------------------------------------------------------------
# build_so_rows - real Desktop oracle header shape
# ---------------------------------------------------------------------------

SO_ORACLE_HEADER_ROW = {
    "Doc No": "SO253362",
    "Doc Date": 44995,
    "Delivery Date": 45019,
    "Debtor Code": "303-I001",
    "Debtor Name": "IDEAL BATH SDN BHD",
    "Agent": "LCL",
    "Ref Doc No": None,
    "Ref": None,
    "Remark 1": None,
    "Item Code": "BRWTPB865104CP",
    "Item Description": "BRAVAT BUILT-IN SHOWER MIXER TRIM SET",
    "Location": "BRW-IB",
    "Qty": 40,
    "Transfered Qty": 1,
    "Remaining Qty": 39,
    "Unit Price": 0,
    "Discount": None,
    "Total (Inc)": 0,
    "Note": "PO-2023/03-0025/ELING",
}


def test_build_so_rows_shapes_header_and_line():
    headers, lines = build_so_rows([SO_ORACLE_HEADER_ROW])
    assert set(headers) == {"SO253362"}
    header = headers["SO253362"]
    assert header["debtor_code"] == "303-I001"
    assert header["debtor_name"] == "IDEAL BATH SDN BHD"
    assert header["sales_agent"] == "LCL"
    assert header["note"] == "PO-2023/03-0025/ELING"

    assert len(lines) == 1
    line = lines[0]
    assert line["doc_no"] == "SO253362"
    assert line["item_code"] == "BRWTPB865104CP"
    assert line["location"] == "BRW-IB"
    assert line["qty"] == 40
    # Netted, NOT the oracle's own "Transfered Qty" column (which says 1).
    assert line["transfered_qty"] == 40 - 39


def test_build_so_rows_multiple_lines_share_one_header():
    row2 = dict(SO_ORACLE_HEADER_ROW)
    row2["Item Code"] = "OTHER-ITEM"
    row2["Remaining Qty"] = 0
    headers, lines = build_so_rows([SO_ORACLE_HEADER_ROW, row2])
    assert len(headers) == 1
    assert len(lines) == 2


def test_build_so_rows_skips_rows_with_no_doc_no_or_item_code():
    no_doc = dict(SO_ORACLE_HEADER_ROW)
    no_doc["Doc No"] = None
    no_item = dict(SO_ORACLE_HEADER_ROW)
    no_item["Doc No"] = "SO_NOITEM"
    no_item["Item Code"] = None
    headers, lines = build_so_rows([no_doc, no_item])
    # The no-item row still registers its header (a header-only row is
    # legitimate in AutoCount - description/subtotal rows) but contributes
    # no line.
    assert "SO_NOITEM" in headers
    assert lines == []


# ---------------------------------------------------------------------------
# build_po_rows - real PO/SPO oracle header shape
# ---------------------------------------------------------------------------

PO_ORACLE_ROW = {
    "Item Code": "CB4924-CR",
    "Qty": 20,
    "Transfered Qty": 20,
    "Remaining Qty": 0,
    "Loading Date": "14.05.23 CMAU7129817",
    "Agent": "TAIYANG",
    "Location": "BRW",
    "Doc No": "202301-S0001",
    "Doc Date": datetime(2023, 1, 3),
    "Delivery Date": datetime(2023, 1, 3),
    "Ref": None,
    "Description": "CABANA BASIN COLD TAP CB4924-CR",
    "Creditor Name": "XIAMEN TAIYANG TECHNOLOGY CO.,LTD",
    "Shipping Order": "Unchecked",
    "FromSODocList": None,
}


def test_build_po_rows_mints_synthetic_creditor_code():
    headers, lines = build_po_rows([PO_ORACLE_ROW])
    header = headers["202301-S0001"]
    assert header["creditor_name"] == "XIAMEN TAIYANG TECHNOLOGY CO.,LTD"
    assert header["creditor_code"] == _creditor_code("XIAMEN TAIYANG TECHNOLOGY CO.,LTD")
    assert header["purchase_agent"] == "TAIYANG"

    line = lines[0]
    assert line["item_code"] == "CB4924-CR"
    assert line["unit_price"] is None  # no Unit Price column in this oracle
    # Netted (Remaining=0 -> fully received): 20 - 0 = 20.
    assert line["transfered_qty"] == 20


def test_build_po_rows_open_line_from_remaining_qty():
    open_row = dict(PO_ORACLE_ROW)
    open_row["Qty"] = 100
    open_row["Remaining Qty"] = 60
    _, lines = build_po_rows([open_row])
    assert lines[0]["transfered_qty"] == 40  # 100 - 60


# ---------------------------------------------------------------------------
# mark_po_rows_open
# ---------------------------------------------------------------------------


def _settled(doc_no: str, item_code: str, qty: float) -> dict:
    return {"doc_no": doc_no, "item_code": item_code, "qty": qty, "transfered_qty": qty}


def test_mark_po_rows_open_flips_only_settled_lines_deterministically():
    lines = [
        _settled("PO-1", "ITEM-A", 10),  # settled
        _settled("PO-2", "ITEM-B", 5),  # settled
        {"doc_no": "PO-3", "item_code": "ITEM-C", "qty": 8, "transfered_qty": 2},  # already open
    ]
    out = mark_po_rows_open(lines, 1)
    assert out[0]["transfered_qty"] == 9  # flipped: qty - 1
    assert out[1]["transfered_qty"] == 5  # untouched (only 1 requested)
    assert out[2]["transfered_qty"] == 2  # already open, untouched

    # Original input never mutated.
    assert lines[0]["transfered_qty"] == 10


def test_mark_po_rows_open_zero_or_negative_n_is_a_no_op():
    lines = [_settled("PO-1", "ITEM-A", 10)]
    out = mark_po_rows_open(lines, 0)
    assert out[0]["transfered_qty"] == 10
    out = mark_po_rows_open(lines, -3)
    assert out[0]["transfered_qty"] == 10


def test_mark_po_rows_open_caps_at_requested_count_even_with_more_candidates():
    lines = [_settled(f"PO-{i}", "ITEM-A", 10) for i in range(5)]
    out = mark_po_rows_open(lines, 2)
    flipped = [r for r in out if r["transfered_qty"] != 10]
    assert len(flipped) == 2


# ---------------------------------------------------------------------------
# clone_spo_docs
# ---------------------------------------------------------------------------


def test_clone_spo_docs_prefixes_docno_and_copies_lines():
    headers = {
        "PO-A": {"doc_no": "PO-A", "creditor_code": "CR-X"},
        "PO-B": {"doc_no": "PO-B", "creditor_code": "CR-Y"},
    }
    lines = [
        {"doc_no": "PO-A", "item_code": "ITEM-1", "qty": 5, "transfered_qty": 5},
        {"doc_no": "PO-B", "item_code": "ITEM-2", "qty": 3, "transfered_qty": 0},
    ]
    new_headers, new_lines = clone_spo_docs(headers, lines, 1)
    # PO-A sorts first -> cloned.
    assert "SPO-PO-A" in new_headers
    assert new_headers["SPO-PO-A"]["doc_no"] == "SPO-PO-A"
    assert "SPO-PO-B" not in new_headers  # only 1 requested

    cloned_lines = [r for r in new_lines if r["doc_no"] == "SPO-PO-A"]
    assert len(cloned_lines) == 1
    assert cloned_lines[0]["item_code"] == "ITEM-1"

    # Originals untouched, inputs not mutated.
    assert set(headers) == {"PO-A", "PO-B"}
    assert len(lines) == 2


def test_clone_spo_docs_zero_n_is_a_no_op():
    headers = {"PO-A": {"doc_no": "PO-A"}}
    lines = [{"doc_no": "PO-A", "item_code": "X"}]
    new_headers, new_lines = clone_spo_docs(headers, lines, 0)
    assert new_headers == headers
    assert new_lines == lines


# ---------------------------------------------------------------------------
# assign_keys - deterministic integer ids
# ---------------------------------------------------------------------------


def test_assign_keys_is_deterministic_and_1_based():
    keys = assign_keys(["SO-B", "SO-A", "SO-C"])
    assert keys == {"SO-A": 1, "SO-B": 2, "SO-C": 3}
    # Re-running with the same set (even reordered / with duplicates) is
    # identical - same input set, same ids.
    again = assign_keys(["SO-C", "SO-A", "SO-B", "SO-A"])
    assert again == keys


def test_assign_keys_reuses_existing_and_never_renumbers():
    """Rig defect (coordinator finding): re-seeding with a different derived
    set (SO + PO books, --open-po/--spo flags) changed WHICH natural keys
    exist, and `assign_keys`'s pure sorted-rank assignment re-minted
    different AutoKeys/DocKeys/DtlKeys for codes that were already present -
    a real AutoCount key never moves once assigned, so the rig must not
    either. Given an existing key map (as read back from the target table on
    a re-run) and the current natural-key set, `assign_keys` must KEEP every
    already-known key exactly as it was and mint brand-new keys (max+1,
    upward from the existing map's own high-water mark) ONLY for codes that
    are genuinely new - never re-rank/re-sort the whole set from scratch.
    """
    existing = {"A": 1, "C": 2}
    keys = assign_keys(["A", "B", "C"], existing=existing)
    assert keys == {"A": 1, "C": 2, "B": 3}


def test_assign_keys_reuse_still_deterministic_for_multiple_new_codes():
    """Two new codes arriving in the same run must still get stable,
    order-independent ids relative to each other (sorted-order tie-break,
    same discipline as the no-existing-map path) - not e.g. insertion order,
    which would make the SAME logical re-seed mint different ids depending
    on incidental dict/list ordering."""
    existing = {"A": 1}
    keys = assign_keys(["A", "Z", "M"], existing=existing)
    assert keys["A"] == 1
    # "M" sorts before "Z" - the new codes still rank deterministically.
    assert keys["M"] == 2
    assert keys["Z"] == 3


# ---------------------------------------------------------------------------
# master derivation
# ---------------------------------------------------------------------------


def test_derive_debtors_from_distinct_so_headers():
    so_headers = {
        "SO-1": {"debtor_code": "300-C001", "debtor_name": "Aurora", "sales_agent": "LCL"},
        "SO-2": {"debtor_code": "300-C001", "debtor_name": "Aurora", "sales_agent": "LCL"},
        "SO-3": {"debtor_code": "300-C002", "debtor_name": "Bright", "sales_agent": "TAN R"},
    }
    debtors = derive_debtors(so_headers)
    assert len(debtors) == 2
    codes = {d["acc_no"] for d in debtors}
    assert codes == {"300-C001", "300-C002"}


def test_derive_creditors_from_distinct_po_headers():
    po_headers = {
        "PO-1": {"creditor_code": "CR-X", "creditor_name": "X Corp", "purchase_agent": "TAIYANG"},
        "PO-2": {"creditor_code": "CR-X", "creditor_name": "X Corp", "purchase_agent": "TAIYANG"},
    }
    creditors = derive_creditors(po_headers)
    assert len(creditors) == 1
    assert creditors[0]["acc_no"] == "CR-X"


def test_derive_items_dedupes_across_so_and_po():
    so_lines = [{"item_code": "ITEM-1", "description": "Widget"}]
    po_lines = [{"item_code": "ITEM-1", "description": "Widget"}, {"item_code": "ITEM-2", "description": "Gadget"}]
    items = derive_items(so_lines, po_lines)
    codes = {i["item_code"] for i in items}
    assert codes == {"ITEM-1", "ITEM-2"}
    assert len(items) == 2


def test_derive_locations_dedupes_across_so_and_po():
    so_lines = [{"location": "WH-KL"}, {"location": None}]
    po_lines = [{"location": "WH-KL"}, {"location": "WH-JB"}]
    locations = derive_locations(so_lines, po_lines)
    assert {l["location"] for l in locations} == {"WH-KL", "WH-JB"}


def test_derive_sales_agents_covers_both_sales_and_purchase_role():
    so_headers = {"SO-1": {"sales_agent": "LCL"}}
    po_headers = {"PO-1": {"purchase_agent": "TAIYANG"}, "PO-2": {"purchase_agent": "LCL"}}
    agents = derive_sales_agents(so_headers, po_headers)
    assert {a["agent"] for a in agents} == {"LCL", "TAIYANG"}
