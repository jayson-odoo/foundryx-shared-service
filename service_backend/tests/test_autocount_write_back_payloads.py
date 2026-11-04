"""Plan 55 S2: pure link / split / unlink payload builders (AC-55-10..16)."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from modules.autocount.write_back.payloads import (
    WriteRefusal,
    build_link,
    build_spo_unlink,
    build_unlink,
    so_outstanding,
)

FIX = Path(__file__).parent / "fixtures" / "autocount_write_back"

HEADER_KEYS = {
    "DocKey", "DocNo", "DocDate", "CreditorCode", "CreditorName", "Ref", "Description",
    "DisplayTerm", "PurchaseAgent", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4",
    "Phone1", "Fax1", "Attention", "BranchCode", "DeliverAddr1", "DeliverAddr2",
    "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1", "DeliverContact",
    "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4",
    "RefDocNo", "ShipVia", "ShipInfo", "InclusiveTax",
}
ROW_KEYS = {
    "DtlKey", "ItemCode", "Location", "Description", "ProjNo", "UOM", "UserUOM", "Qty",
    "FOCQty", "UnitPrice", "Discount", "TaxCode", "DeliveryDate", "Desc2", "FromDocType",
    "FromDocNo", "FromDocDtlKey", "FullTransferOption", "FullTransferFromDocList",
}
FORBIDDEN_ROW = {"SubTotal", "SmallestQty", "Seq", "FromSODtlKey", "LocalSubTotal", "TaxableAmt"}


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture()
def po():
    return _load("po_202602_S0007.json")


@pytest.fixture()
def so():
    return _load("so_SO389293.json")


@pytest.fixture()
def spo():
    return _load("spo_db1_sample.json")


def _row(doc, key):
    return next(r for r in doc["Details"] if r["DtlKey"] == key)


def D(v):
    return Decimal(str(v))


def _refusal(code, fn, *a, **kw):
    with pytest.raises(WriteRefusal) as ei:
        fn(*a, **kw)
    assert ei.value.code == code
    return ei.value


# ---- so_outstanding ----------------------------------------------------

def test_ac_55_13_so_outstanding(so):
    r = _row(so, 11996)
    assert so_outstanding(r, Decimal(0)) == Decimal(9)
    assert so_outstanding(r, Decimal(4)) == Decimal(5)
    assert so_outstanding(r, Decimal(9)) == Decimal(0)
    assert so_outstanding(r, Decimal(12)) == Decimal(0)  # clamped
    assert so_outstanding({"Qty": 0.1}, Decimal("0.03")) == Decimal("0.07")


# ---- AC-55-14 same qty: in place -------------------------------------------

def test_ac_55_14_same_qty_edits_in_place_and_moves_location(po, so):
    body = build_link(po, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    # PO row 12009 qty 1 @BRW-AM item SRTKS7090; SO 11990 same item qty 10, outstanding 1
    assert len(body["Details"]) == 1
    row = body["Details"][0]
    assert row["DtlKey"] == 12009
    assert row["FromDocType"] == "SO"
    assert row["FromDocNo"] == "SO389293"
    assert row["FromDocDtlKey"] == 11990
    assert row["Location"] == "BRW-AM"
    assert D(row["Qty"]) == 1


def test_ac_55_14_same_qty_location_changes_in_place(po, so):
    po2 = copy.deepcopy(po)
    _row(po2, 12009)["Location"] = "HQ"
    body = build_link(po2, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert len(body["Details"]) == 1
    assert body["Details"][0]["Location"] == "BRW-AM"
    assert body["Details"][0]["DtlKey"] == 12009


# ---- AC-55-10 link in place ------------------------------------------------

def test_ac_55_10_header_whitelist_and_docKey(po, so):
    body = build_link(po, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert body["DocKey"] == 12008
    header = {k for k in body if k != "Details"}
    assert header <= HEADER_KEYS
    for k in ("DocKey", "DocNo", "CreditorCode", "CurrencyCode", "DocDate"):
        assert body[k] == po[k]
    for k in ("Total", "NetTotal", "Cancelled", "LastModified", "DocStatus", "ShippingPO"):
        assert k not in body


def test_ac_55_10_row_whitelist_and_copied_fields(po, so):
    body = build_link(po, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    row = body["Details"][0]
    assert set(row) <= ROW_KEYS
    assert not (set(row) & FORBIDDEN_ROW)
    src = _row(po, 12009)
    for k in ("ItemCode", "UOM", "UserUOM", "UnitPrice", "Discount", "TaxCode", "Description", "Desc2", "ProjNo"):
        assert row[k] == src[k]


def test_ac_55_10_only_touched_row_sent(po, so):
    body = build_link(po, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    keys = [r["DtlKey"] for r in body["Details"]]
    assert keys == [12009]
    assert 12011 not in keys  # linked rows are never re-sent


# ---- AC-55-11 split --------------------------------------------------------

def test_ac_55_11_split_real_case_srtkt38ss(po, so):
    body = build_link(po, 12017, so, 11989, Decimal(10))
    assert len(body["Details"]) == 2
    edited = next(r for r in body["Details"] if r["DtlKey"] == 12017)
    new = next(r for r in body["Details"] if r["DtlKey"] == 0)
    assert D(edited["Qty"]) == 40
    assert edited["Location"] == "HQ"
    assert edited["FromDocType"] == ""
    assert edited["FromDocNo"] == ""
    assert edited["FromDocDtlKey"] == 0
    assert D(new["Qty"]) == 10
    assert new["Location"] == "BRW-AM"
    assert new["FromDocType"] == "SO"
    assert new["FromDocNo"] == "SO389293"
    assert new["FromDocDtlKey"] == 11989
    assert new["FOCQty"] == 0
    src = _row(po, 12017)
    for k in ("ItemCode", "UOM", "UserUOM", "UnitPrice", "Discount", "TaxCode", "DeliveryDate", "Description", "Desc2", "ProjNo"):
        assert new[k] == src[k]
    for r in body["Details"]:
        assert set(r) <= ROW_KEYS
        assert not (set(r) & FORBIDDEN_ROW)


def test_ac_55_11_split_decimal_exact(po, so):
    po2 = copy.deepcopy(po)
    _row(po2, 12017)["Qty"] = 10.0
    body = build_link(po2, 12017, so, 11989, Decimal("3.3"))
    edited = next(r for r in body["Details"] if r["DtlKey"] == 12017)
    new = next(r for r in body["Details"] if r["DtlKey"] == 0)
    assert D(edited["Qty"]) == Decimal("6.7")
    assert D(new["Qty"]) == Decimal("3.3")
    assert D(edited["Qty"]) + D(new["Qty"]) == Decimal(10)
    assert isinstance(edited["Qty"], (int, float)) and isinstance(new["Qty"], (int, float))


def test_ac_55_11_split_keeps_existing_link_fields_of_edited_row_free_row(po, so):
    # the edited (remaining) row stays unlinked because the source row was unlinked
    body = build_link(po, 12017, so, 11992, Decimal(4))
    edited = next(r for r in body["Details"] if r["DtlKey"] == 12017)
    assert D(edited["Qty"]) == 46
    assert edited["Location"] == "HQ"


# ---- AC-55-13 refusals -----------------------------------------------------

def test_ac_55_13_item_mismatch(po, so):
    _refusal("ITEM_MISMATCH", build_link, po, 12017, so, 11990, Decimal(1))  # SRTKT38SS vs SRTKS7090


def test_ac_55_13_uom_mismatch(po, so):
    so2 = copy.deepcopy(so)
    _row(so2, 11990)["UOM"] = "BOX"
    _refusal("UOM_MISMATCH", build_link, po, 12009, so2, 11990, Decimal(1), so_linked_qty=Decimal(9))


@pytest.mark.parametrize("q", [Decimal(0), Decimal(-1)])
def test_ac_55_13_qty_invalid(po, so, q):
    _refusal("QTY_INVALID", build_link, po, 12009, so, 11990, q)


def test_ac_55_13_qty_above_free(po, so):
    _refusal("QTY_ABOVE_FREE", build_link, po, 12009, so, 11990, Decimal(2))  # PO row Qty 1


def test_ac_55_13_qty_above_outstanding_real_case(po, so):
    # SO row 11996 qty 9 fully linked already (so_linked_qty 9). PO row 12009 is item SRTKS7090.
    _refusal("QTY_ABOVE_OUTSTANDING", build_link, po, 12009, so, 11996, Decimal(1), so_linked_qty=Decimal(9))


def test_ac_55_13_already_linked(po, so):
    _refusal("ROW_ALREADY_LINKED", build_link, po, 12011, so, 11990, Decimal(1))


def test_ac_55_13_po_cancelled(po, so):
    po2 = copy.deepcopy(po)
    po2["Cancelled"] = "T"
    _refusal("DOC_CANCELLED", build_link, po2, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))


def test_ac_55_13_spo_passed_as_po(spo, so):
    _refusal("DOC_KIND_MISMATCH", build_link, spo, spo["Details"][0]["DtlKey"], so, 11990, Decimal(1))


def test_ac_55_13_row_not_found(po, so):
    _refusal("ROW_NOT_FOUND", build_link, po, 999999, so, 11990, Decimal(1))
    _refusal("ROW_NOT_FOUND", build_link, po, 12009, so, 999999, Decimal(1))


def test_ac_55_13_unlink_cancelled_and_kind(po, spo):
    po2 = copy.deepcopy(po)
    po2["Cancelled"] = "T"
    _refusal("DOC_CANCELLED", build_unlink, po2, 12011)
    _refusal("DOC_KIND_MISMATCH", build_unlink, spo, spo["Details"][0]["DtlKey"])
    _refusal("ROW_NOT_FOUND", build_unlink, po, 999999)


# ---- AC-55-15 SPO precondition ---------------------------------------------

def test_ac_55_15_link_refused_when_spo_points_at_row(po, so):
    e = _refusal("ROW_ON_SPO", build_link, po, 12009, so, 11990, Decimal(1), spo_ref="SPO-2026/11-0001")
    assert "SPO-2026/11-0001" in str(e)


def test_ac_55_15_unlink_refused_when_spo_points_at_row(po):
    e = _refusal("ROW_ON_SPO", build_unlink, po, 12011, spo_ref="SPO-2026/11-0001")
    assert "SPO-2026/11-0001" in str(e)


def test_ac_55_15_spo_unlink_body(spo):
    row = spo["Details"][0]
    body = build_spo_unlink(spo, row["DtlKey"])
    assert body["DocKey"] == spo["DocKey"]
    assert body["DocNo"] == spo["DocNo"]
    assert {k for k in body if k != "Details"} <= HEADER_KEYS
    assert len(body["Details"]) == 1
    r = body["Details"][0]
    assert r["DtlKey"] == row["DtlKey"]
    assert r["FromDocType"] == "" and r["FromDocNo"] == "" and r["FromDocDtlKey"] == 0
    assert D(r["Qty"]) == D(row["Qty"])
    assert r["Location"] == row["Location"]
    assert set(r) <= ROW_KEYS


def test_ac_55_15_spo_unlink_refusals(po, spo):
    _refusal("DOC_KIND_MISMATCH", build_spo_unlink, po, 12011)
    _refusal("ROW_NOT_FOUND", build_spo_unlink, spo, 999999)
    spo2 = copy.deepcopy(spo)
    spo2["Details"][0]["FromDocType"] = ""
    spo2["Details"][0]["FromDocNo"] = ""
    spo2["Details"][0]["FromDocDtlKey"] = 0
    _refusal("ROW_NOT_LINKED", build_spo_unlink, spo2, spo2["Details"][0]["DtlKey"])


# ---- AC-55-12 / AC-55-16 unlink --------------------------------------------

def test_ac_55_12_unlink_real_row_12013(po):
    body = build_unlink(po, 12013)
    assert body["DocKey"] == 12008
    assert {k for k in body if k != "Details"} <= HEADER_KEYS
    assert [r["DtlKey"] for r in body["Details"]] == [12013]
    r = body["Details"][0]
    assert r["FromDocType"] == "" and r["FromDocNo"] == "" and r["FromDocDtlKey"] == 0
    assert D(r["Qty"]) == 10
    assert r["Location"] == "HQ"
    assert set(r) <= ROW_KEYS
    assert not (set(r) & FORBIDDEN_ROW)


def test_ac_55_12_unlink_not_linked_refused(po):
    _refusal("ROW_NOT_LINKED", build_unlink, po, 12009)


def test_ac_55_16_split_row_unlink_stays_own_row(po):
    # a row that was split off earlier: linked, qty 3, BRW-AM. Unlink keeps qty/location, no merge.
    po2 = copy.deepcopy(po)
    split = copy.deepcopy(_row(po2, 12013))
    split.update(DtlKey=12020, Qty=3.0, Location="BRW-AM", FromSODtlKey=11993)
    po2["Details"].append(split)
    body = build_unlink(po2, 12020)
    assert len(body["Details"]) == 1
    r = body["Details"][0]
    assert r["DtlKey"] == 12020
    assert D(r["Qty"]) == 3
    assert r["Location"] == "BRW-AM"
    assert r["FromDocType"] == ""
    assert r["FromDocDtlKey"] == 0


# ---- purity ----------------------------------------------------------------

def test_builders_do_not_mutate_inputs(po, so):
    po_before, so_before = copy.deepcopy(po), copy.deepcopy(so)
    build_link(po, 12017, so, 11989, Decimal(10))
    build_unlink(po, 12013)
    assert po == po_before and so == so_before


# ---- vendor finding (live run C07): dates below 1753 are omitted -----------------------

EMPTY = "0001-01-01T00:00:00"


def _all_rows(body):
    return body["Details"]


def test_vendor_unlink_real_row_12013_omits_the_empty_delivery_date(po):
    assert _row(po, 12013)["DeliveryDate"] == EMPTY
    body = build_unlink(po, 12013)
    assert "DeliveryDate" not in body["Details"][0]
    assert body["DocDate"] == po["DocDate"]


def test_vendor_link_in_place_omits_empty_date_keeps_valid_one(po, so):
    po2 = copy.deepcopy(po)
    _row(po2, 12009)["DeliveryDate"] = EMPTY
    body = build_link(po2, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert "DeliveryDate" not in body["Details"][0]
    body_ok = build_link(po, 12009, so, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert body_ok["Details"][0]["DeliveryDate"] == "2026-03-15T00:00:00"


def test_vendor_split_omits_empty_date_on_edited_and_new_row(po, so):
    po2 = copy.deepcopy(po)
    _row(po2, 12017)["DeliveryDate"] = EMPTY
    body = build_link(po2, 12017, so, 11989, Decimal(10))
    assert len(body["Details"]) == 2
    assert all("DeliveryDate" not in r for r in body["Details"])


def test_vendor_split_keeps_a_valid_date_on_both_rows(po, so):
    body = build_link(po, 12017, so, 11989, Decimal(10))
    assert [r["DeliveryDate"] for r in body["Details"]] == ["2026-03-15T00:00:00"] * 2


def test_vendor_missing_date_stays_missing(po, so):
    po2 = copy.deepcopy(po)
    del _row(po2, 12017)["DeliveryDate"]
    body = build_link(po2, 12017, so, 11989, Decimal(10))
    assert all("DeliveryDate" not in r for r in body["Details"])
    unlink = build_unlink(po2, 12013)
    assert "DeliveryDate" not in unlink["Details"][0]


@pytest.mark.parametrize("value,kept", [
    ("1752-12-31T00:00:00", False),
    ("0001-01-01", False),
    ("1753-01-01T00:00:00", True),
    ("2026-03-15T00:00:00", True),
])
def test_vendor_date_cutoff_is_year_1753(po, value, kept):
    po2 = copy.deepcopy(po)
    _row(po2, 12013)["DeliveryDate"] = value
    row = build_unlink(po2, 12013)["Details"][0]
    assert ("DeliveryDate" in row) is kept
    if kept:
        assert row["DeliveryDate"] == value


def test_vendor_spo_unlink_omits_empty_date_keeps_valid(spo):
    spo2 = copy.deepcopy(spo)
    spo2["Details"][0]["DeliveryDate"] = EMPTY
    body = build_spo_unlink(spo2, spo2["Details"][0]["DtlKey"])
    assert "DeliveryDate" not in body["Details"][0]
    ok = build_spo_unlink(spo, spo["Details"][0]["DtlKey"])
    assert ok["Details"][0]["DeliveryDate"] == "2026-10-29T00:00:00"


def test_vendor_header_docdate_always_stays(po):
    body = build_unlink(po, 12013)
    assert body["DocDate"] == "2026-02-04T00:00:00"
