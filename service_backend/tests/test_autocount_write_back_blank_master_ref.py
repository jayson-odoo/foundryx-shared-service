"""SS-AC-BLANK-MASTER-REF: a master-reference header code read back blank is never sent.

db3 6 Nov: PO DocKey 12127 created without a purchase agent read back
``"PurchaseAgent": ""``; the split link copied it into the edit PUT and AutoCount
answered 500 "The value of column PurchaseAgent ... does not exist in its master file".
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from modules.autocount.write_back import payloads as P
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

FIX = Path(__file__).parent / "fixtures" / "autocount_write_back"
BLANKS = ("", "   ", None)


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _po(agent):
    doc = _load("po_202602_S0007.json")
    doc["PurchaseAgent"] = agent
    return doc


def _spo(agent):
    doc = _load("spo_db1_sample.json")
    doc["PurchaseAgent"] = agent
    return doc


def _sales(name, agent):
    doc = copy.deepcopy(_load(name)["after"])
    doc["SalesAgent"] = agent
    return doc


SO = _load("so_SO389293.json")


@pytest.mark.parametrize("agent", BLANKS)
def test_split_link_skips_blank_purchase_agent(agent):
    body = P.build_link(_po(agent), 12009, SO, 11990, Decimal(1), so_linked_qty=Decimal(9), whole_row_as_split=True)
    assert len(body["Details"]) == 2 and body["Details"][1]["DtlKey"] == 0  # a split
    assert "PurchaseAgent" not in body


@pytest.mark.parametrize("agent", BLANKS)
def test_whole_link_unlink_relocate_skip_blank_purchase_agent(agent):
    assert "PurchaseAgent" not in P.build_link(_po(agent), 12009, SO, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert "PurchaseAgent" not in P.build_unlink(_po(agent), 12011)
    assert "PurchaseAgent" not in P.build_relocate(_po(agent), 12011, "KL")


@pytest.mark.parametrize("agent", BLANKS)
def test_spo_unlink_skips_blank_purchase_agent(agent):
    spo = _spo(agent)
    key = next(r["DtlKey"] for r in spo["Details"] if r.get("FromDocDtlKey") or r.get("FromDocNo"))
    assert "PurchaseAgent" not in P.build_spo_unlink(spo, key)


def test_present_purchase_agent_is_still_sent():
    """Kill test: only a BLANK code is omitted."""
    body = P.build_link(_po("AGENT"), 12009, SO, 11990, Decimal(1), so_linked_qty=Decimal(9))
    assert body["PurchaseAgent"] == "AGENT"
    assert P.build_edit("PO", _po("AGENT"), {"Ref": "x"}, []).body["PurchaseAgent"] == "AGENT"
    assert P.build_edit("SO", _sales("so_P-SO0.json", "VIXX"), {"Ref": "x"}, []).body["SalesAgent"] == "VIXX"


@pytest.mark.parametrize("agent", BLANKS)
def test_level1_po_edit_add_cancel_skip_blank_purchase_agent(agent):
    po = _po(agent)
    assert "PurchaseAgent" not in P.build_edit("PO", po, {"Ref": "x"}, [{"DtlKey": 12009, "Qty": 2}]).body
    line = {"ItemCode": "X", "UOM": "UNIT", "Qty": 1, "UnitPrice": 1, "Location": "HQ"}
    assert "PurchaseAgent" not in P.build_add_line("PO", po, line).body
    po["Details"] = [r for r in po["Details"] if not r.get("FromSODtlKey")]
    assert "PurchaseAgent" not in P.build_cancel("PO", po).body


@pytest.mark.parametrize("agent", BLANKS)
@pytest.mark.parametrize("kind,name", [("SO", "so_P-SO0.json"), ("QT", "qt_P-QT1.json")])
def test_so_qt_edit_skips_blank_sales_agent(kind, name, agent):
    doc = _sales(name, agent)
    key = doc["Details"][0]["DtlKey"]
    assert "SalesAgent" not in P.build_edit(kind, doc, {"Ref": "x"}, [{"DtlKey": key, "Qty": 2}]).body
    if kind == "QT":
        assert "SalesAgent" not in P.build_cancel(kind, doc).body


MASTER_REFS = ("PurchaseAgent", "SalesAgent", "DisplayTerm", "BranchCode", "CurrencyCode", "ShipVia")


@pytest.mark.parametrize("key", MASTER_REFS)
def test_every_master_ref_key_blank_is_omitted(key):
    """Every master-reference code in the whitelist: blank read-back -> not sent."""
    po = _po("AGENT")
    po[key] = ""
    assert key not in P.build_edit("PO", po, {"Ref": "x"}, []).body
    assert key not in P.header_of(po)
    so = _sales("so_P-SO0.json", "VIXX")
    so[key] = " "
    assert key not in P.build_edit("SO", so, {"Ref": "x"}, []).body
    assert key not in P.so_header_of(so)


def test_non_master_blank_field_is_still_sent():
    """Free-text fields keep their blank (clearing a remark must still work)."""
    po = _po("")
    po["Remark1"] = ""
    assert P.build_edit("PO", po, {}, []).body["Remark1"] == ""


def test_master_ref_keys_are_all_whitelisted_header_fields():
    assert set(MASTER_REFS) | {"CreditorCode", "DebtorCode"} == P.MASTER_REF_HEADER_KEYS
    assert P.MASTER_REF_HEADER_KEYS <= set(P.HEADER_KEYS) | set(P.SO_HEADER_KEYS)
